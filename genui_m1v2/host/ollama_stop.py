"""專用 Ollama 停止證據狀態機（附件 §J、v3.1b §J'；M1 演算法說明 v3 補充第 5 節，使用者 11/16 13:58「五塊照說明」）。
純邏輯：Windows Job Object 等實際操作由 backend 提供（PC 上用 ctypes 實作；雲端測試用假 backend）。
等待上限 STOP_WAIT_S、DONE_GRACE_S 為候選值〔待凍結〕。"""
STOP_VERSION = "ollamastop-m1-0.2"
# 0.2（v3.1c J1～J2，使用者 11/18 20:58「v3.1c 照草案」）：
#   啟動拆成「暫停建立 → 放進 Job → 恢復」，放進 Job 失敗就結束那個暫停程序、不恢復；
#   取消時握著 Job 控制代碼結束 Job，拿到「程序數 0＋埠釋放」證據後才關控制代碼；
#   正常完成要 done:true、回應本體完整結束、讀取沒有錯誤。Linux 路徑 v1 停用。
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
        if hasattr(self.b, "assign_to_job"):
            self.b.create_suspended(port)
            if not self.b.assign_to_job():                          # J1：納管失敗 → 結束暫停程序、不恢復
                self.b.terminate_suspended(); self.log.append("assign_failed"); return "ASSIGN_FAILED"
        else:
            self.b.create_suspended_in_job(port)                    # 0.1 介面（暫停建立並放進 Job）
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

    def finish(self, got_done, http_closed_within, body_complete=True, read_error=False):
        """got_done：收到 done:true；http_closed_within：HTTP 回應結束花的秒數（None＝沒結束）；
        body_complete：chunked 結尾或 content-length 讀滿；read_error：讀取有錯誤（J2）。"""
        if got_done and http_closed_within is not None and http_closed_within <= DONE_GRACE_S and body_complete and not read_error:
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
            if hasattr(self.b, "close_job_handle"):
                self.b.close_job_handle()                           # J1：拿到證據後才關控制代碼
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
