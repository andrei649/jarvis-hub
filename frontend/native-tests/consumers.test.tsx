import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { AppearanceProvider } from '../../mobile/src/context/AppearanceContext';
import { records } from './support/storage';
import { foreground } from './support/native';
import App from '../../mobile/App';
import { AgentPicker } from '../../mobile/src/components/AgentPicker';
import { MessageBubble } from '../../mobile/src/components/MessageBubble';
import { SessionsModal } from '../../mobile/src/components/SessionsModal';
import { Markdown } from '../../mobile/src/markdown/Markdown';
import { AcquisitionScreen } from '../../mobile/src/screens/AcquisitionScreen';
import { AmbientScreen } from '../../mobile/src/screens/AmbientScreen';
import { ApprovalsScreen } from '../../mobile/src/screens/ApprovalsScreen';
import { CameraScreen } from '../../mobile/src/screens/CameraScreen';
import { CaptureScreen } from '../../mobile/src/screens/CaptureScreen';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { CommsScreen } from '../../mobile/src/screens/CommsScreen';
import { HouseScreen } from '../../mobile/src/screens/HouseScreen';
import { MediaScreen } from '../../mobile/src/screens/MediaScreen';
import { MemoryScreen } from '../../mobile/src/screens/MemoryScreen';
import { SettingsScreen } from '../../mobile/src/screens/SettingsScreen';
import { SkillsScreen } from '../../mobile/src/screens/SkillsScreen';
import { StatusScreen } from '../../mobile/src/screens/StatusScreen';
import { TasksScreen } from '../../mobile/src/screens/TasksScreen';
let preferences:any;
beforeEach(()=>{
  records.clear();records.set('jarvis.server.config.v1',JSON.stringify({baseUrl:'https://fixture.test',token:'',adminToken:''}));
  preferences={accent:'cyan',look:'obsidian',font:'theme'};
  global.fetch=vi.fn(async url=>({ok:true,status:200,json:async()=>String(url).endsWith('/api/preferences/appearance')?{configured:true,preferences}:{enabled:false,items:[],agents:[],sessions:[],notes:[],skills:[],tasks:[],devices:[],records:[],monitors:[],cameras:[],status:'offline'}}));
});
afterEach(cleanup);
const noop=()=>{};
const consumers:any[]=[
  ['App',App,{},true],['AgentPicker',AgentPicker,{value:'jarvis',onChange:noop}],
  ['MessageBubble',MessageBubble,{message:{id:'one',role:'user',text:'fixture text'}}],
  ['SessionsModal',SessionsModal,{visible:true,onClose:noop,onResume:noop}],['Markdown',Markdown,{text:'fixture text'}],
  ...Object.entries({AcquisitionScreen,AmbientScreen,ApprovalsScreen,CameraScreen,CaptureScreen,ChatScreen,CommsScreen,HouseScreen,MediaScreen,MemoryScreen,SettingsScreen,SkillsScreen,StatusScreen,TasksScreen}).map(([name,component])=>[name,component,{onGoToSettings:noop,onGoToApprovals:noop}]),
];
const styles=(container:HTMLElement)=>Array.from(container.querySelectorAll('[data-native-style]')).map(node=>node.getAttribute('data-native-style')).join('\n');
it.each(consumers)('%s updates mounted native styles after foreground appearance refresh',async(_name,Component,props,ownsProvider)=>{
  const child=<Component {...props}/>;
  const {container}=render(ownsProvider?child:<ServerProvider><AppearanceProvider>{child}</AppearanceProvider></ServerProvider>);
  await waitFor(()=>expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/preferences/appearance'),expect.anything()));
  const before=styles(container);
  preferences={accent:'violet',look:'graphite',font:'system-serif'};
  await act(async()=>{foreground('background');foreground('active');});
  await waitFor(()=>expect(styles(container)).not.toBe(before));
  expect(styles(container)).toContain('Georgia');
});

it('paints the default Nerva theme and repaints mounted styles when the browser theme changes',async()=>{
  preferences={accent:'cyan',look:'ledger',font:'theme'};
  const {container}=render(<App/>);
  await waitFor(()=>expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/preferences/appearance'),expect.anything()));
  expect(styles(container)).toContain('#0e1210');   // Ledger · Carbon ground
  // the seal's vermilion is the owner's hand: tabs, links and buttons take Ledger's ink, never #fd6c48
  expect(styles(container)).toContain('#dde4db');
  expect(styles(container)).not.toContain('#fd6c48');
  preferences={accent:'cyan',look:'atlas',font:'theme'};
  await act(async()=>{foreground('background');foreground('active');});
  await waitFor(()=>expect(styles(container)).toContain('#070a09'));
  expect(styles(container)).not.toContain('#0e1210');
});

it('keeps independent code monospace and mounted text-input state on font changes',async()=>{
  const {container,getByPlaceholderText}=render(<ServerProvider><AppearanceProvider><SettingsScreen/><Markdown text={'prose\n\n```\ncode\n```'}/></AppearanceProvider></ServerProvider>);
  await waitFor(()=>expect(fetch).toHaveBeenCalled());
  const field=getByPlaceholderText('192.168.1.20:8000');
  const {fireEvent}=await import('@testing-library/react');fireEvent.change(field,{target:{value:'typed-but-not-saved'}});
  preferences={accent:'amber',look:'graphite',font:'system-serif'};
  await act(async()=>{foreground('background');foreground('active');});
  await waitFor(()=>expect(styles(container)).toContain('Georgia'));
  expect((field as HTMLInputElement).value).toBe('typed-but-not-saved');
  expect(styles(container)).toContain('Menlo');
});

it('explains the native JetBrains fallback and read-only synchronization in Settings',async()=>{
  preferences={accent:'cyan',look:'obsidian',font:'jetbrains-mono'};
  const {getByText}=render(<ServerProvider><AppearanceProvider><SettingsScreen/></AppearanceProvider></ServerProvider>);
  await waitFor(()=>expect(getByText(/JetBrains Mono.*platform monospace/)).toBeTruthy());
  expect(getByText(/Appearance.*synced/)).toBeTruthy();
  expect(getByText(/Change appearance in the browser/)).toBeTruthy();
});

it('keeps primary destinations reachable and opens secondary destinations from More', async () => {
  const { container } = render(<App />);
  expect(container.querySelectorAll('[aria-label$=" tab"]').length).toBe(3);
  for (const label of ['Chat tab', 'Tasks tab', 'Skills tab', 'More destinations']) {
    const button = screen.getByLabelText(label);
    expect(JSON.parse(button.getAttribute('data-native-style') || '{}').minHeight).toBeGreaterThanOrEqual(44);
  }
  fireEvent.click(screen.getByLabelText('More destinations'));
  expect(screen.getByLabelText('Open Settings')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Open Settings'));
  expect(screen.queryByLabelText('Close More menu')).toBeNull();
  fireEvent.click(screen.getByLabelText('More destinations'));
  expect(screen.getByLabelText('Open Settings, current destination')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Close More menu'));
  expect(screen.queryByLabelText('Open Settings, current destination')).toBeNull();
  fireEvent.click(screen.getByLabelText('More destinations'));
  fireEvent.click(screen.getByLabelText('Open Memory'));
  fireEvent.click(screen.getByLabelText('Skills tab'));
  fireEvent.click(screen.getByLabelText('Chat tab'));
  await waitFor(() => expect(screen.getByText('No hub connected')).toBeTruthy());
  expect(screen.getByText('Jarvis')).toBeTruthy();
});
