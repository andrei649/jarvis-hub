import React from 'react';
import {render,screen,fireEvent} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {TopBar} from '../shell';

it('offers a direct topbar entry to the dedicated automation workspace',()=>{
 const open=vi.fn();
 render(<TopBar {...({clock:new Date(0),lang:"en",agents:[],t:{},onJobs:open} as any)}/>);
 fireEvent.click(screen.getByRole('button',{name:'Automations'}));
 expect(open).toHaveBeenCalledOnce();
});
