/** Stop the page scrolling under an overlay, without the layout jumping when the scrollbar goes. */
export function lockScroll() {
  const html = document.documentElement
  const gap = window.innerWidth - html.clientWidth
  const prev = { overflow: html.style.overflow, padding: html.style.paddingRight }
  html.style.overflow = 'hidden'
  if (gap > 0) html.style.paddingRight = `${gap}px`
  return () => {
    html.style.overflow = prev.overflow
    html.style.paddingRight = prev.padding
  }
}
