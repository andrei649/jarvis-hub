import React, {useState} from 'react';
import {fireEvent, render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {OptionsEditor, type JobOptions} from './job-builder';

const catalog = [{id:'basic',tools:['echo','time'],available:true},{id:'files',tools:['file_read'],available:false}];
function Editor({initial={repeat:2}}:{initial?:JobOptions}) {
  const [value,setValue]=useState(initial);
  return <><OptionsEditor value={value} onChange={setValue} toolsets={catalog}/><output>{JSON.stringify(value)}</output></>;
}
it('authors no tools, explicit installed groups and default without dropping other options',()=>{
  render(<Editor/>);
  fireEvent.change(screen.getByLabelText('job toolsets mode'),{target:{value:'none'}});
  expect(screen.getByRole('status').textContent).toBe('{"repeat":2,"enabled_toolsets":[]}');
  fireEvent.change(screen.getByLabelText('job toolsets mode'),{target:{value:'selected'}});
  fireEvent.click(screen.getByLabelText('toolset basic'));
  expect(screen.getByRole('status').textContent).toContain('"enabled_toolsets":["basic"]');
  expect((screen.getByLabelText('toolset files') as HTMLInputElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('job toolsets mode'),{target:{value:'default'}});
  expect(screen.getByRole('status').textContent).toBe('{"repeat":2}');
});
it('keeps unavailable saved IDs visible and removable',()=>{
  render(<Editor initial={{enabled_toolsets:['removed']}}/>);
  expect(screen.getByText(/removed.*unavailable/)).toBeTruthy();
  fireEvent.click(screen.getByLabelText('toolset removed'));
  expect(screen.getByRole('status').textContent).toContain('"enabled_toolsets":[]');
});
