"""
Qt worker thread so OCR / conversion don't freeze the UI.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class Worker(QObject):
    finished = Signal(object)   # result payload
    failed = Signal(str)        # error message

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # surfaced to the UI, not swallowed
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)


def run_async(parent, fn, *args, on_done=None, on_error=None, **kwargs):
    """
    Spin a function onto a QThread. Returns (thread, worker); keep a reference
    on the caller so they aren't garbage-collected mid-run.
    """
    thread = QThread(parent)
    worker = Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    if on_done:
        worker.finished.connect(on_done)
    if on_error:
        worker.failed.connect(on_error)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(thread.deleteLater)

    thread.start()
    return thread, worker
