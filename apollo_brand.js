/* The hand-drawn A in ios/Artwork/apollo-original-a.svg is Apollo's mark. */
(() => {
  const paths = '<path d="M5 25 L14.5 6 L27 25" stroke-width="1.8"/><path d="M6.5 20 C11 15.5 18 14.5 27 19" stroke-width="1.35"/>';
  const selectors = [
    '.apollo-boot-logo svg', '.brand-mark svg', '.apollo-nav-sun svg',
    '.apollo-welcome-mark svg', '.apollo-mobile-chat-mark svg',
    '.apollo-presence-handle svg', '.apollo-image-generating-mark svg',
    '.apollo-message-mark svg'
  ].join(',');
  function apply(root = document) {
    const marks = root.matches?.(selectors) ? [root] : [];
    root.querySelectorAll?.(selectors).forEach(mark => marks.push(mark));
    for (const svg of marks) {
      if (svg.dataset.apolloOriginal === 'true' && !svg.querySelector('rect, circle')) continue;
      svg.setAttribute('viewBox', '0 0 32 32');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      svg.innerHTML = paths;
      svg.dataset.apolloOriginal = 'true';
    }
  }
  apply();
  document.addEventListener('DOMContentLoaded', () => apply());
  const messages = document.getElementById('apolloMessages');
  if (messages) new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) {
      if (node.nodeType === Node.ELEMENT_NODE) apply(node);
    }
  }).observe(messages, {childList: true, subtree: true});
})();
