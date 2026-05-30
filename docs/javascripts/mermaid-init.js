document$.subscribe(() => {
  if (window.mermaid) {
    window.mermaid.initialize({ startOnLoad: true });
    window.mermaid.run();
  }
});
