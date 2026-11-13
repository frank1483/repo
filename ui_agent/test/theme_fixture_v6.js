'use strict';
// Theme UI/Settings are mocked; color validation remains the production pure JS.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
function load(name,deps={}) {
    const scope={...deps};vm.createContext(scope);
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../qml',name),'utf8')
        .replace(/^\.(?:pragma|import)[^\n]*\n/gm,''),scope,{filename:name});
    return scope;
}
const ThemePalette=load('GcpAgentThemePalette.js',{ColorMath:load('GcpAgentThemeColorMath.js')});
const source=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentState.qml'),'utf8');
function extract(name) {
    const start=source.indexOf('    function '+name+'(');assert(start>=0,name);
    const line=source.indexOf('\n',start);
    const end=source.indexOf('\n    }',line);assert(end>start,name);
    return source.slice(start,end+6).trim();
}
exports.install=function(scope) {
    scope.ThemePalette=ThemePalette;scope._themeGroups={};scope._themeLoadPending=false;scope.themePolicy=null;
    if(scope.GcpTheme)scope.GcpTheme.color={setAgentThemeGroups(){}};
    if(scope._savedFingerprint){const value=JSON.parse(scope._savedFingerprint);value.themeGroups={};scope._savedFingerprint=JSON.stringify(value);}
    vm.createContext(scope);
    vm.runInContext(['_requireThemeLayoutReady','_checkedTheme','_writeThemeGroups'].map(extract).join('\n'),scope);
    return scope;
};
