import { createRoot } from 'react-dom/client';
import App from './app';
import { isFloatingDesktop } from './desktop';
import { OwnerSignIn } from './owner-sign-in';
import { applyInitialAppearance } from './theme/apply';
import './styles.css';
import './theme/index.css';

// Theme contract v1 §7: the cached appearance goes onto <html> before React renders, so the first
// paint is already in the owner's theme (index.html carries the default theme until this runs).
applyInitialAppearance();

createRoot(document.getElementById('root')!).render(
  <>
    {isFloatingDesktop() ? <App floating /> : <App />}
    <OwnerSignIn />
  </>,
);
