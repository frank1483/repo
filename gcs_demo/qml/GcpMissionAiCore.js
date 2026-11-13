.pragma library
// 任務規劃面板的純邏輯（不碰 QML 物件，可用 node 測）。演算法與模型都在伺服器（gcs_demo.server :8765 → 閘道 :8090）；
// 這裡只負責：規劃頁航點 → /api/plan 的 mission、候選 → 新的航點順序、結果的來源標籤。QML 裡沒有規則備援。

// wps: [{lat, lon, alt}]（規劃頁一般航點，依目前順序）；home: {lat, lon}；optional: {"WP2": true}
function missionBody(wps, home, optional, speedMps, name) {
    if (!wps || wps.length < 1 || !home) return null
    var targets = []
    for (var i = 0; i < wps.length; i++) {
        var id = "WP" + (i + 1)
        targets.push({ id: id, lat: wps[i].lat, lon: wps[i].lon, alt: wps[i].alt, required: !(optional && optional[id]) })
    }
    var alt = wps[0].alt
    return { name: name || "目前任務", home: { lat: home.lat, lon: home.lon },
             cruise_alt_m: (typeof alt === "number" && alt >= 5 && alt <= 120) ? alt : 50,
             speed_mps: speedMps || 8, targets: targets }
}

// 套用前後比對：規劃後航點被改過就要重新規劃
function signature(body) { return body ? JSON.stringify(body) : "" }

function sourceTag(pick) {
    if (!pick) return { zh: "", kind: "none" }
    if (pick.source === "llm") return { zh: "模型選擇", kind: "llm" }
    return { zh: pick.llm ? "規則（模型未成功，已退回）" : "規則", kind: "rule" }
}

function reportTag(rep) {
    if (!rep) return { zh: "", kind: "none" }
    if (rep.source === "llm") return { zh: "模型撰寫", kind: "llm" }
    return { zh: rep.llm ? "規則撰寫（模型未成功，已退回）" : "規則撰寫", kind: "rule" }
}

function find(cands, id) {
    for (var i = 0; cands && i < cands.length; i++) if (cands[i].id === id) return cands[i]
    return null
}

function applicable(c) { return !!c && c.feasible && !c.sorties && !c.requires_battery_swap }

// snapshot: 套用前規劃頁航點 [{lat,lon,alt}]（WPn 對應 snapshot[n-1]）；cand.order: ["WP3","WP1",...]
// 回傳 {points: 新順序的航點, dropped: 被拿掉的選配點 id}；只用到原有的座標，不產生新點
function reorder(snapshot, cand) {
    if (!applicable(cand)) return null
    var points = [], used = {}
    for (var i = 0; i < cand.order.length; i++) {
        var m = /^WP(\d+)$/.exec(cand.order[i])
        var k = m ? parseInt(m[1], 10) - 1 : -1
        if (k < 0 || k >= snapshot.length || used[k]) return null
        used[k] = true
        points.push(snapshot[k])
    }
    var dropped = []
    for (var j = 0; j < snapshot.length; j++) if (!used[j]) dropped.push("WP" + (j + 1))
    return { points: points, dropped: dropped }
}

function pickedId(res) {
    if (!res || !res.pick) return ""
    return res.pick.choice_id || res.rule_choice || ""
}

if (typeof module !== "undefined") module.exports = { missionBody: missionBody, signature: signature, sourceTag: sourceTag,
    reportTag: reportTag, find: find, applicable: applicable, reorder: reorder, pickedId: pickedId }
