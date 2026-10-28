// Offline source-to-patch helper for Claude. Never changes the supplied formal UI.
// node ui_agent/tools/build_full_text_scale_patch.cjs <formal-copy-root> <new-output-directory>
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const src=path.resolve(process.argv[2]||''),out=path.resolve(process.argv[3]||'');
if(!process.argv[2]||!process.argv[3]||src===out||out.startsWith(src+path.sep)||fs.existsSync(out))
    throw Error('Supply a formal UI COPY and a new output directory outside that copy');
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
let scanned=0,themeCount=0,directCount=0,patch='',entries=[],sources=[];
function walk(d){let result=[];for(const e of fs.readdirSync(d,{withFileTypes:true})){
    if(++scanned>2000)throw Error('Scan budget exceeded (2000 entries)');
    if(e.name==='Agent')continue;const f=path.join(d,e.name);
    if(e.isDirectory())result.push(...walk(f));else if(f.endsWith('.qml'))result.push(f);
}return result;}
for(const f of walk(path.join(src,'GCP'))){
    const name=path.relative(src,f).replaceAll(path.sep,'/'),bytes=fs.readFileSync(f),old=bytes.toString('utf8').replace(/\r\n/g,'\n');
    sources.push({file:name,sha256:sha(bytes)});let neu=old;
    if(name==='GCP/GcpThemeFont.qml'){
        if(/property\s+real\s+textScale/.test(old))throw Error('Theme already has textScale; rebase explicitly');
        neu=neu.replace('    id: root','    id: root\n    property real textScale: 1.0');
        neu=neu.replace(/(readonly property (?:real|int) (\w+):\s*)(\d+(?:\.\d+)?)(\s*(?:\/\/[^\n]*)?)$/gm,(all,start,prop,n,end)=>{
            themeCount++;entries.push({file:name,property:prop,base:Number(n)});return start+n+' * root.textScale'+end;
        });
    } else {
        neu=neu.split('\n').map((line,i)=>{
            if(line.trim().startsWith('//'))return line;
            return line.replace(/font\.pixelSize:\s*(\d+(?:\.\d+)?)(?=\s*[;}]|\s*$)/g,(all,n)=>{
                directCount++;entries.push({file:name,line:i+1,base:Number(n)});return 'font.pixelSize: ('+n+' * GcpTheme.font.textScale)';
            });
        }).join('\n');
    }
    if(neu!==old){
        const aa=old.trimEnd().split('\n'),bb=neu.trimEnd().split('\n');
        // Full-file hunks are intentional: exact-source review before integration.
        patch+='--- a/'+name+'\n+++ b/'+name+'\n@@ -1,'+aa.length+' +1,'+bb.length+' @@\n'+aa.map(l=>'-'+l).join('\n')+'\n'+bb.map(l=>'+'+l).join('\n')+'\n';
    }
}
fs.mkdirSync(out,{recursive:false});
const audit={theme_properties:themeCount,direct_numeric_lines:directCount,expected_theme:251,expected_direct:84,sources,entries,
    limitation:'Numeric font.pixelSize sites only; grouped font { pixelSize: ... }, comments/strings and imports require source review. No tests or UI execution.'};
fs.writeFileSync(path.join(out,'font_scan_audit.first.json'),JSON.stringify(audit,null,2)+'\n',{flag:'wx'});
if(themeCount!==251||directCount!==84)throw Error('Source count mismatch; FIRST audit retained; no complete patch published');
fs.writeFileSync(path.join(out,'elan_gcp_text_scale_complete.patch'),patch,{flag:'wx'});
console.log(JSON.stringify({theme_properties:themeCount,direct_numeric_lines:directCount,patch_sha256:sha(patch),status:'DRAFT_REQUIRES_IMPORT_AND_QT_REVIEW'}));
