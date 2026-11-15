.pragma library
// SHA-256（UTF-8 輸入，十六進位輸出）。純 JS，給 RouteRecord 的 input_hash 用。
function utf8Bytes(str) {
    var out = [], s = String(str)
    for (var i = 0; i < s.length; ++i) {
        var c = s.charCodeAt(i)
        if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
            var d = s.charCodeAt(i + 1)
            if (d >= 0xdc00 && d <= 0xdfff) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); ++i }
        }
        if (c < 0x80) out.push(c)
        else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63))
        else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63))
        else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63))
    }
    return out
}
var K = []
;(function () {
    var n = 2, count = 0
    while (count < 64) {
        var prime = true
        for (var d = 2; d * d <= n; ++d) if (n % d === 0) { prime = false; break }
        if (prime) { var f = Math.pow(n, 1 / 3); K.push(Math.floor((f - Math.floor(f)) * 4294967296) >>> 0); ++count }
        ++n
    }
})()
function sha256Hex(str) {
    var b = utf8Bytes(str), bits = b.length * 8
    b.push(0x80)
    while (b.length % 64 !== 56) b.push(0)
    var hi = Math.floor(bits / 4294967296), lo = bits >>> 0
    b.push((hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255, (lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255)
    var h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]
    function rotr(x, n) { return (x >>> n) | (x << (32 - n)) }
    var w = new Array(64)
    for (var off = 0; off < b.length; off += 64) {
        for (var i = 0; i < 16; ++i) w[i] = ((b[off + 4 * i] << 24) | (b[off + 4 * i + 1] << 16) | (b[off + 4 * i + 2] << 8) | b[off + 4 * i + 3]) >>> 0
        for (i = 16; i < 64; ++i) {
            var s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3)
            var s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10)
            w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0
        }
        var a = h[0], bb = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7]
        for (i = 0; i < 64; ++i) {
            var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25), ch = (e & f) ^ (~e & g)
            var t1 = (hh + S1 + ch + K[i] + w[i]) >>> 0
            var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22), maj = (a & bb) ^ (a & c) ^ (bb & c)
            var t2 = (S0 + maj) >>> 0
            hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = bb; bb = a; a = (t1 + t2) >>> 0
        }
        h[0] = (h[0] + a) >>> 0; h[1] = (h[1] + bb) >>> 0; h[2] = (h[2] + c) >>> 0; h[3] = (h[3] + d) >>> 0
        h[4] = (h[4] + e) >>> 0; h[5] = (h[5] + f) >>> 0; h[6] = (h[6] + g) >>> 0; h[7] = (h[7] + hh) >>> 0
    }
    var out = ""
    for (i = 0; i < 8; ++i) out += ("00000000" + h[i].toString(16)).slice(-8)
    return out
}
