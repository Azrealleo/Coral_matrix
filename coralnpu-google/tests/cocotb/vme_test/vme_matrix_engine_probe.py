"""Read-only VPI observer; needs the dedicated selective-public model."""

import cocotb
from cocotb.handle import HierarchyArrayObject, HierarchyObject
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

from vme_matrix_engine_counter import ArrayCounter

SIGNAL_WIDTHS = {
    "clk": 1, "rst_n": 1, "flush": 1, "busy": 1, "cnt": 2,
    "canStart": 1, "hitRaw": 1, "blkCmdVld": 4, "blkCmdRdy": 4,
    "peCmdVld": 4, "peCmdRdy": 4, "peRtVld": 4,
    "writeEn": 256, "writeMtIdx": 64, "writeSubIdx": 64, "writePc": 128,
}


class ZvtArrayProbe:
    def __init__(self, dut):
        matches = []

        def walk(node, parent=None, depth=0):
            assert depth < 24, "Unexpectedly deep VPI hierarchy"
            if node._name.rsplit(".", 1)[-1] == "zvtPeArray":
                matches.append((node, parent))
                return
            for child in node:
                if isinstance(child, (HierarchyObject, HierarchyArrayObject)):
                    walk(child, node, depth + 1)

        walk(dut)
        assert len(matches) == 1, (
            f"Expected one zvtPeArray, found {len(matches)}. "
            "Run the vme_matrix_engine model/target, not the ordinary VME model."
        )
        self.array, parent = matches[0]
        self.handles = {name: getattr(self.array, name) for name in SIGNAL_WIDTHS}
        for name, width in SIGNAL_WIDTHS.items():
            try:
                observed_width = len(self.handles[name])
            except TypeError:
                # Cocotb 2 scalar LogicObject has no array-length interface.
                assert width == 1 and type(self.handles[name]).__name__ == "LogicObject"
                observed_width = 1
            assert observed_width == width, f"{name}: unsupported geometry"
        self.mt_write = getattr(parent, "writeEn")
        assert len(self.mt_write) == 256
        self.clock = self.handles["clk"]
        self.counter = None
        self.task = None
        self.error = None
        cocotb.log.info(f"[GOOGLE_ARRAY_PROBE] path={self.array._path} geometry=VLEN128_TM16_TN16_TK4")

    def start(self):
        assert self.task is None
        self.counter = ArrayCounter()
        self.error = None
        self.task = cocotb.start_soon(self._observe())

    async def _observe(self):
        try:
            while True:
                # Verilator's RisingEdge resumes after RTL evaluation. Capture
                # the settled falling-edge state for the FOLLOWING rising edge.
                # This clock has no falling-edge sequential logic in the array.
                await FallingEdge(self.clock)
                await ReadOnly()
                sample = {name: int(handle.value) for name, handle in self.handles.items() if name != "clk"}
                sample["mtWriteEn"] = int(self.mt_write.value)
                await RisingEdge(self.clock)
                self.counter.step(sample)
        except Exception as error:
            self.error = error

    def stop(self):
        if self.task is not None:
            self.task.kill()
            self.task = None

    def summary(self, k):
        if self.error is not None:
            raise AssertionError(f"Array probe rejected this run: {self.error}") from self.error
        return self.counter.summary(k)
