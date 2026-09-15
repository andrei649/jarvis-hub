import { createRoot } from 'react-dom/client';
import App from './world_app';
import ChatApp from './app';
import { isFloatingDesktop } from './desktop';
import './styles.css';

createRoot(document.getElementById('root')!).render(isFloatingDesktop() ? <ChatApp floating /> : <App />);
