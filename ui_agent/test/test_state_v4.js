// Production state JS functions with mocked QML properties. No Qt/Settings/device/HTTP execution.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert'),Core=require('./load_core');
const src=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentState.qml'),'utf8');
const names=['snapshot','_restore','checkedLayout','beginChange','beginGroup','commitGroup','rollbackGroup','undo','redo','resetAll','setTextScale','loadSavedLayout','saveCurrentLayout','layoutFingerprint','defaultLayout'];
function extract(name){
    const marker='    function '+name+'(',start=src.indexOf(marker);assert(start>=0,'missing production function '+name);
    const lineEnd=src.indexOf('\n',start),head=src.slice(start,lineEnd);
    if(head.trimEnd().endsWith('}'))return head.trim();
    const end=src.indexOf('\n    }',lineEnd);assert(end>=0,'missing function end '+name);return src.slice(start,end+6).trim();
}
const logs=[];let loc={page:0,section:-1},syncs=0;
const sandbox={Core,JSON,Object,Array,Number,isFinite,Error,Math,console:{warn:s=>logs.push(s)},
    GcpTheme:{font:{textScale:1}},revision:0,_modules:{},_overrides:{},_cancelRedo:[],undoStack:[],redoStack:[],_groupActive:false,_savedLoaded:true,_savedCorrupt:false,_savedFingerprint:'{"overrides":{},"textScale":1}',
    _layoutSettings:{savedLayoutJson:'',layoutsJson:'{}',sync(){syncs++}},_apply(){},
    shell:{agentLocation:()=>({...loc}),agentGoTo:(page,section)=>{loc={page,section};return true}},
    qsTr:s=>s};
Object.defineProperty(sandbox,'textScale',{get(){return sandbox.GcpTheme.font.textScale}});
vm.createContext(sandbox);vm.runInContext(names.map(extract).join('\n'),sandbox);
const S=sandbox,plain=x=>JSON.parse(JSON.stringify(x));
const dirty=()=>S.layoutFingerprint()!==S._savedFingerprint;
const cp=S.beginGroup();S.beginChange('navigation','navigation');S.shell.agentGoTo(1,-1);S.beginChange('wind','layout');
S._overrides={windGauge:{rx:0.1,ry:0.1,scale:2,hidden:false}};assert.strictEqual(syncs,0);S.commitGroup();assert.strictEqual(syncs,0);assert(dirty());
S.saveCurrentLayout();assert.strictEqual(syncs,1);assert(!dirty());
S.undo(1);assert.strictEqual(loc.page,1);assert.deepStrictEqual(plain(S._overrides),{});
S.undo(1);assert.strictEqual(loc.page,0);S.redo();assert.strictEqual(loc.page,1);S.redo();assert.strictEqual(S._overrides.windGauge.scale,2);
assert.strictEqual(syncs,1);assert(!dirty());
S.undo(1);const redoBefore=plain(S.redoStack),undoBefore=plain(S.undoStack),savedBefore=S._layoutSettings.savedLayoutJson;
const failed=S.beginGroup();S.beginChange('nav','navigation');S.shell.agentGoTo(2,-1);S.beginChange('bad layout','layout');S.setTextScale(1.3);S.rollbackGroup(failed);
assert.strictEqual(loc.page,1);assert.strictEqual(S.textScale,1);assert.deepStrictEqual(plain(S.redoStack),redoBefore);assert.deepStrictEqual(plain(S.undoStack),undoBefore);assert.strictEqual(S._layoutSettings.savedLayoutJson,savedBefore);
const font=S.beginGroup();S.beginChange('font','layout');S.setTextScale(1.15);S.commitGroup();S.undo(1);assert.strictEqual(S.textScale,1);S.redo();assert.strictEqual(S.textScale,1.15);
assert.strictEqual(syncs,1);assert.strictEqual(S._layoutSettings.savedLayoutJson,savedBefore);assert(dirty());
assert.strictEqual(S.checkedLayout({layoutVersion:2,page:0,section:-1,overrides:{}}).textScale,1);
function restart(){S._savedLoaded=false;S._overrides={};S.GcpTheme.font.textScale=1;S.undoStack=[];S.redoStack=[];S.shell.agentGoTo(0,-1);S.loadSavedLayout();}
restart();assert.strictEqual(S.textScale,1);assert.strictEqual(S._overrides.windGauge.scale,2);assert.strictEqual(loc.page,0);assert.strictEqual(S.undoStack.length,0);assert(!dirty());
S.setTextScale(0.85);S.saveCurrentLayout();assert.strictEqual(syncs,2);const explicitlySaved=S._layoutSettings.savedLayoutJson;
S.defaultLayout();assert.strictEqual(S.textScale,1);assert(dirty());assert.strictEqual(S._layoutSettings.savedLayoutJson,explicitlySaved);restart();assert.strictEqual(S.textScale,0.85);assert.strictEqual(S._overrides.windGauge.scale,2);
S._layoutSettings.savedLayoutJson='{invalid';S._savedLoaded=false;S.loadSavedLayout();assert.strictEqual(S.textScale,1);assert(S._savedCorrupt);S.setTextScale(1.3);assert.throws(()=>S.saveCurrentLayout());assert.strictEqual(S._layoutSettings.savedLayoutJson,'{invalid');assert(logs.length>0);
console.log('PASS production state JS under mocks; Qt runtime and durable Settings remain unverified');
