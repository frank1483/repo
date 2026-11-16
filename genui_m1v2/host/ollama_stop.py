"""專用 Ollama 停止證據狀態機（附件 §J、v3.1b §J'；M1 演算法說明 v3 補充第 5 節，使用者 11/16 13:58「五塊照說明」）。
純邏輯：Windows Job Object 等實際操作由 backend 提供（PC 上用 ctypes 實作；雲端測試用假 backend）。
等待上限 STOP_WAIT_S、DONE_GRACE_S 為候選值〔待凍結〕。"""
STOP_VERSION = "ollamastop-m1-0.1"
DONE_GRACE_S = 2.0
STOP_WAIT_S = 5.0

class Slot:
    def __init__(self, backend, clock):
        self.b, self.clock = backend, clock
        self.disabled = False
        self.flags = None
        self.log = []

    def start(self, port):
        if self.disabled:
            return "MODEL_PAUSED"
        if self.b.port_in_use(port):
            self.log.append("port_busy"); return "PORT_BUSY"        # 停下回報，不沿用
        self.b.create_suspended_in_job(port)                        # 暫停狀態建立 → 放進 Job（關閉時結束全部子程序）
        self.b.resume()
        self.port = port; self.log.append("started"); return "STARTED"

    def begin_request(self):
        self.flags = {"result_routed": False, "stop_evidence": False, "slot_returned": False}

    def _wait_stopped(self):
        t0 = self.clock()
        while self.clock() - t0 <= STOP_WAIT_S:
            if self.b.job_process_count() == 0 and not self.b.port_in_use(self.port):
                return True
            self.b.sleep(0.1)
        return False

    def finish(self, got_done, http_closed_within):
        """got_done：收到 done:true；http_closed_within：HTTP 回應結束花的秒數（None＝沒結束）。"""
        if got_done and http_closed_within is not None and http_closed_within <= DONE_GRACE_S:
            self.flags.update(result_routed=True, stop_evidence=True)
            self.log.append("done_normal")
            return self._release()
        return self.cancel("done_without_close" if got_done else "cancel")

    def cancel(self, why):
        self.b.close_connection()
        self.b.terminate_job()
        self.flags["result_routed"] = True                          # 結果去向：丟棄並記錄
        self.log.append("cancel:" + why)
        if self._wait_stopped():
            self.flags["stop_evidence"] = True
            r = self._release()
            self.b.restart(self.port); self.log.append("restarted")
            return r
        self.disabled = True                                       # 停用桌面模型路徑，全部走規則版；不重試、不動 Job 以外程序
        self.log.append("stop_unconfirmed")
        return "MODEL_PAUSED"

    def _release(self):
        self.flags["slot_returned"] = True
        return "SLOT_FREE" if all(self.flags.values()) else "SLOT_HELD"

    def can_hand_over(self):
        return (not self.disabled) and self.flags is not None and all(self.flags.values())
