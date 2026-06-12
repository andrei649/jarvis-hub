'use strict';
/* WorldView Redesign — app root: zones, mode system, tweaks */
const { useState:uAS } = React;
const { AppBar, LegendPanel, ReconPanel, StatsPanel, InspectorPanel, AlertsPanel, ExportPanel,
  Timeline, FirstRun, HelpOverlay, MapCanvas, GlobeCanvas, ArrivalBanner, DemoLens,
  useTweaks, TweaksPanel, TweakSection, TweakRadio, TweakSelect, TweakToggle } = window;

const WVR_DEFAULTS = /*EDITMODE-BEGIN*/{
  "scenario": "demo",
  "inspectorOpen": true,
  "helpOpen": false,
  "lens": false
}/*EDITMODE-END*/;

function WvrApp(){
  const [t,setTweak]=useTweaks(WVR_DEFAULTS);
  const arrival = t.scenario==='arrival';
  const mode=arrival?'replay':t.scenario;
  const firstrun = mode==='firstrun';
  const frameMode = firstrun?'offline':mode;
  const [layers,setLayers]=uAS(['adsb','ais','tle','ew','context']);
  const [view,setView]=uAS('map');
  const [tour,setTour]=uAS(false);
  const [insp,setInsp]=uAS(true);
  const showInsp = (t.inspectorOpen??true)&&insp&&!firstrun&&mode!=='offline';

  return (
    <div className="wvr">
      <div className={'mode-frame '+frameMode}></div>
      <AppBar mode={firstrun?'offline':mode} view={view} setView={setView} tourOn={tour} setTour={setTour}
        onGoLive={()=>setTweak('scenario','live')} onHelp={()=>setTweak('helpOpen',true)}/>
      <div className="stage">
        <div className={'mapwrap'+((firstrun||mode==='offline')?' dim':'')}>
          {view==='globe'
            ? <GlobeCanvas layers={firstrun?[]:layers} selected={showInsp} tour={tour}/>
            : <MapCanvas layers={firstrun?[]:layers} selected={showInsp} mode={mode}/>}
        </div>
        {mode==='demo'&&!firstrun&&<div className="demo-wm">◐ SYNTHETIC FEED — NOT REAL-WORLD DATA</div>}
        {arrival && <ArrivalBanner onDismiss={()=>setTweak('scenario','replay')}/>}
        {t.lens&&!firstrun&&<DemoLens onOff={()=>setTweak('lens',false)}/>}
        {!firstrun && <>
          <div className="zone-left">
            <LegendPanel layers={layers} setLayers={setLayers}/>
            <ReconPanel/>
          </div>
          <div className="zone-right">
            <StatsPanel mode={mode}/>
            {showInsp && <InspectorPanel onClose={()=>setInsp(false)}/>}
            <AlertsPanel onLocate={()=>setInsp(true)}/>
            <div style={{flex:1}}></div>
            <ExportPanel/>
          </div>
        </>}
        {firstrun && <FirstRun onRetry={()=>setTweak('scenario','demo')}/>}
        {t.helpOpen && <HelpOverlay onClose={()=>setTweak('helpOpen',false)}/>}
      </div>
      <Timeline mode={firstrun?'offline':mode} onGoLive={()=>setTweak('scenario','live')}
        onScrub={()=>mode!=='offline'&&setTweak('scenario','historical')}/>

      <TweaksPanel>
        <TweakSection label="State matrix"/>
        <TweakSelect label="Scenario" value={t.scenario}
          options={['live','demo','historical','replay','offline','firstrun','arrival']}
          onChange={v=>setTweak('scenario',v)}/>
        <TweakToggle label="Demo lens (tour grade)" value={t.lens??false} onChange={v=>setTweak('lens',v)}/>
        <TweakToggle label="Inspector open" value={t.inspectorOpen??true} onChange={v=>{setTweak('inspectorOpen',v);setInsp(true);}}/>
        <TweakToggle label="Help overlay" value={t.helpOpen??false} onChange={v=>setTweak('helpOpen',v)}/>
      </TweaksPanel>
    </div>
  );
}
ReactDOM.createRoot(document.getElementById('root')).render(<WvrApp/>);
