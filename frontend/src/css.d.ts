// Allow side-effect CSS imports (e.g. `import './styles.css'`) under `tsc --noEmit`.
// Vite handles the actual bundling at build time; this only satisfies the type checker.
declare module '*.css';
