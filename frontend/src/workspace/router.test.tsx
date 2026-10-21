import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import {
  appPathFromLink, hrefFor, isOutsideApp, Link, matchRoute, navigate, resolveRoute, toAppPath, useLocation,
} from './router';
import { setLocation } from './test/mockApi';

afterEach(() => {
  delete window.__NERVA_BASE_PATH__;
  setLocation('/');
});

describe('path mapping', () => {
  it('maps /workspace URLs to in-app paths and rejects others', () => {
    expect(toAppPath('/workspace')).toBe('/');
    expect(toAppPath('/workspace/')).toBe('/');
    expect(toAppPath('/workspace/admin/users/')).toBe('/admin/users');
    expect(toAppPath('/workspaces/x')).toBeNull();
    expect(toAppPath('/v2/')).toBeNull();
  });

  it('honours the deployment base path both ways', () => {
    window.__NERVA_BASE_PATH__ = '/nerva';
    expect(toAppPath('/nerva/workspace/profile')).toBe('/profile');
    expect(toAppPath('/workspace/profile')).toBeNull();
    expect(hrefFor('/profile')).toBe('/nerva/workspace/profile');
    expect(hrefFor('/')).toBe('/nerva/workspace/');
  });

  it('follows only server links that point inside the Workspace', () => {
    expect(appPathFromLink('/workspace/approvals/12')).toBe('/approvals/12');
    expect(appPathFromLink('/workspace/report-runs/3?x=1')).toBe('/report-runs/3?x=1');
    expect(appPathFromLink('https://evil.example/workspace/x')).toBeNull();
    expect(appPathFromLink('//evil.example/workspace/x')).toBeNull();
    expect(appPathFromLink('/v2/')).toBeNull();
    expect(appPathFromLink('')).toBeNull();
    window.__NERVA_BASE_PATH__ = '/nerva';
    expect(appPathFromLink('/workspace/approvals/1')).toBe('/approvals/1');
    expect(appPathFromLink('/nerva/workspace/approvals/1')).toBe('/approvals/1');
  });
});

describe('matching', () => {
  it('matches segment by segment and decodes parameters', () => {
    expect(matchRoute('/assistant/:conversationId', '/assistant/42')).toEqual({ conversationId: '42' });
    expect(matchRoute('/admin/:section', '/admin/a%20b')).toEqual({ section: 'a b' });
    expect(matchRoute('/assistant', '/assistant/42')).toBeNull();
    expect(matchRoute('/assistant/:id', '/assistant')).toBeNull();
    expect(matchRoute('/a/:id', '/a/%E0%A4%A')).toBeNull();
  });

  it('resolves the first matching route', () => {
    const routes = [{ path: '/admin', render: () => 'a' }, { path: '/admin/:section', render: () => 'b' }];
    expect(resolveRoute(routes, '/admin/users')?.params).toEqual({ section: 'users' });
    expect(resolveRoute(routes, '/nope')).toBeNull();
  });
});

function Where() {
  const location = useLocation();
  return <p data-testid="where">{isOutsideApp(location) ? 'outside' : location.path}</p>;
}

describe('navigation', () => {
  it('pushes history and re-renders subscribers; Link navigates on plain clicks only', () => {
    setLocation('/workspace/assistant');
    // The outer handler stops jsdom's own navigation for the modified click (it has no browser).
    render(<><Where /><div onClick={(e) => e.preventDefault()}><Link to="/profile">Profil</Link></div></>);
    expect(screen.getByTestId('where').textContent).toBe('/assistant');

    fireEvent.click(screen.getByText('Profil'), { ctrlKey: true });
    expect(screen.getByTestId('where').textContent).toBe('/assistant');

    fireEvent.click(screen.getByText('Profil'));
    expect(window.location.pathname).toBe('/workspace/profile');
    expect(screen.getByTestId('where').textContent).toBe('/profile');

    act(() => navigate('/admin/users', { replace: true }));
    expect(screen.getByTestId('where').textContent).toBe('/admin/users');
    expect(screen.getByText('Profil').getAttribute('href')).toBe('/workspace/profile');
  });

  it('reacts to the browser back button and flags URLs outside the app', () => {
    setLocation('/elsewhere');
    render(<Where />);
    expect(screen.getByTestId('where').textContent).toBe('outside');
    act(() => {
      window.history.pushState(null, '', '/workspace/documents');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(screen.getByTestId('where').textContent).toBe('/documents');
  });
});
