.pragma library
// 面板（主畫面浮動層）與航線接收端（任務規劃頁插槽）之間的共用登記處。
// 任務規劃頁只有在顯示時才載入，所以接收端出現／消失時自己登記／取消；面板只透過這裡寫航點。
var sink = null

function register(s) { sink = s }
function unregister(s) { if (sink === s) sink = null }
function current() { return sink }
