// Interface language. Chinese is the source dictionary; the others must match its shape.

import en from './en'
import ja from './ja'
import zh, { type Messages } from './zh'

export const LOCALES = [
  { id: 'zh', name: '中文', lang: 'zh-CN' },
  { id: 'en', name: 'English', lang: 'en' },
  { id: 'ja', name: '日本語', lang: 'ja' },
] as const
export type Locale = (typeof LOCALES)[number]['id']

const DICTS: Record<Locale, Messages> = { zh, en, ja }
const isLocale = (value: unknown): value is Locale => typeof value === 'string' && value in DICTS

function initialLocale(): Locale {
  try {
    const saved = localStorage.getItem('locale')
    if (isLocale(saved)) return saved
  } catch {
    // Private mode: fall back to the browser's languages.
  }
  for (const tag of navigator.languages ?? [navigator.language]) {
    const base = tag.toLowerCase().split('-')[0]
    if (isLocale(base)) return base
  }
  return 'en'
}

const state = $state({ locale: initialLocale() })

function applyLang() {
  document.documentElement.lang = LOCALES.find((l) => l.id === state.locale)!.lang
}
applyLang()

export function getLocale(): Locale {
  return state.locale
}

export function setLocale(locale: Locale) {
  state.locale = locale
  applyLang()
  try {
    localStorage.setItem('locale', locale)
  } catch {
    // Private mode: the choice just does not persist.
  }
}

/** The messages of the current language. Reading it in a template or `$derived` tracks language changes. */
export const t = (): Messages => DICTS[state.locale]

/** Splits a message at its `%s` marker, so that markup (a code span, a link) can go in between. */
export function around(text: string): [string, string] {
  const at = text.indexOf('%s')
  return at < 0 ? [text, ''] : [text.slice(0, at), text.slice(at + 2)]
}
