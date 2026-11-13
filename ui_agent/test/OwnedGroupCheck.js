.pragma library
// Test infrastructure only. No production transaction or State method is replaced.
// Every group this helper may roll back must have been returned to this scope.
function run(name, state, prepare, work) {
    var owned = [], open = true
    var entry = state._groupActive ? state._activeGroupCheckpoint : null
    var row = {name: name, ok: false, cleanup: {attempted: 0, rolledBack: 0, errors: [], foreignActive: false}}
    function fail(message) {
        if (row.error === undefined) row.error = message
        row.ok = false
    }
    var scope = {
        beginGroup: function() {
            if (!open) throw new Error("closed check scope")
            // If begin throws (for example, nested group), no token is owned.
            var token = state.beginGroup()
            owned.push(token)
            return token
        }
    }
    try {
        if (prepare) prepare()
        work(scope)
        row.ok = true
    } catch (error) {
        fail(String(error))
    } finally {
        open = false
        for (var i = owned.length - 1; i >= 0; --i) {
            var token = owned[i]
            if (!state._groupActive || state._activeGroupCheckpoint !== token) continue
            // A successful check must not silently abandon an uncommitted group.
            if (row.ok) fail("check left an owned group open")
            ++row.cleanup.attempted
            try {
                state.rollbackGroup(token)
                if (state._groupActive && state._activeGroupCheckpoint === token)
                    throw new Error("rollback returned with owned group still active")
                ++row.cleanup.rolledBack
            } catch (error) {
                // Preserve the first assertion/setup error independently of cleanup failure.
                row.cleanup.errors.push(String(error))
                fail("owned-group cleanup failed")
            }
        }
        var current = state._groupActive ? state._activeGroupCheckpoint : null
        if (current !== null && current !== entry && owned.indexOf(current) < 0) {
            row.cleanup.foreignActive = true
            fail("unowned group remains active; cleanup skipped")
        }
    }
    return row
}
