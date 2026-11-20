/** Keeps the browser tab named and iconed as Chives; dsh sets its own title at load. */
import { CHIVES_FAVICON_SVG } from './tokens.ts'

export const DOCUMENT_TITLE = '老韭菜 · A股AI研究平台'

interface BrandDocument {
  title: string
  head: Element
  querySelectorAll(selector: string): ArrayLike<Element>
  createElement(tag: string): Element
}

/** Apply title + favicon now and re-assert the title if something else rewrites it. Returns a cleanup. */
export function installDocumentBrand(doc: BrandDocument | undefined = typeof document === 'undefined' ? undefined : (document as unknown as BrandDocument)): () => void {
  if (!doc) return () => {}
  const href = `data:image/svg+xml,${encodeURIComponent(CHIVES_FAVICON_SVG)}`
  const applyIcon = (): void => {
    const links = Array.from(doc.querySelectorAll('link[rel~="icon"]'))
    if (links.length === 0) {
      const link = doc.createElement('link')
      link.setAttribute('rel', 'icon')
      link.setAttribute('type', 'image/svg+xml')
      link.setAttribute('href', href)
      doc.head.appendChild(link)
      return
    }
    for (const link of links) {
      link.setAttribute('type', 'image/svg+xml')
      link.removeAttribute('media')
      if (link.getAttribute('href') !== href) link.setAttribute('href', href)
    }
  }
  const apply = (): void => {
    if (doc.title !== DOCUMENT_TITLE) doc.title = DOCUMENT_TITLE
    applyIcon()
  }
  apply()
  if (typeof MutationObserver === 'undefined') return () => {}
  const observer = new MutationObserver(apply)
  observer.observe(doc.head, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['href', 'media'] })
  return () => observer.disconnect()
}
