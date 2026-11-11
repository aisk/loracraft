// What a good dataset looks like, by what the LoRA is meant to learn.
//
// The figures are the ranges the community has settled on for SDXL LoRAs. They are advice, not
// limits: training runs with any number of images.

import { splitTags, type DatasetImage, type Project } from './api'
import { t } from './i18n/index.svelte'

export interface KindGuide {
  min: number // below this the result is usually unreliable
  max: number // beyond this more images add little
}

export const SMALL_SIDE = 768 // images whose short side is below this are flagged

export const GUIDES: Record<Project['kind'], KindGuide> = {
  character: { min: 15, max: 50 },
  style: { min: 30, max: 150 },
  concept: { min: 20, max: 60 },
}

/** What to look for in the images, for this kind of LoRA and then for every kind. */
export const kindTips = (kind: Project['kind']) => [...t().guide.tips[kind], ...t().guide.commonTips(SMALL_SIDE)]

export const kindNoun = (kind: Project['kind']) => t().guide.nouns[kind]

export const countRange = (kind: Project['kind']) => t().guide.countRange(GUIDES[kind].min, GUIDES[kind].max)

export function countAdvice(kind: Project['kind'], count: number): { ok: boolean; text: string } {
  const { min, max } = GUIDES[kind]
  const m = t().guide
  if (count < min) return { ok: false, text: m.tooFew(count, m.nouns[kind], min) }
  if (count > max) return { ok: true, text: m.plenty(count) }
  return { ok: true, text: m.enough(count) }
}

// Tags that say nothing about how varied a dataset is.
const COUNT_TAGS = new Set(['solo', '1girl', '1boy', '1other'])
const QUALITY_TAGS = new Set(['masterpiece', 'best quality', 'high quality', 'highres', 'absurdres', 'very aesthetic', 'newest'])

const CONSTANT_SHARE = 0.9
const CONSTANT_MIN_IMAGES = 8 // with fewer captions than this, "nearly every image" means little

/**
 * Tags carried by nearly every captioned image. Whatever never varies gets learned together with
 * the subject, so these point either at missing variety or at traits to drop from the captions.
 */
export function constantTags(project: Project, images: DatasetImage[]): string[] {
  const captioned = images.filter((image) => image.caption)
  if (captioned.length < CONSTANT_MIN_IMAGES) return []
  const counts = new Map<string, number>()
  for (const image of captioned) for (const tag of new Set(splitTags(image.caption))) counts.set(tag, (counts.get(tag) ?? 0) + 1)
  return [...counts.entries()]
    .filter(([tag, count]) => {
      if (tag === project.trigger || QUALITY_TAGS.has(tag)) return false
      if (project.kind !== 'style' && COUNT_TAGS.has(tag)) return false
      // Sentences are not tags: a clause repeated everywhere is not a variety signal worth listing.
      if (tag.split(/\s+/).length > 4) return false
      return count / captioned.length >= CONSTANT_SHARE
    })
    .sort((a, b) => b[1] - a[1])
    .map(([tag]) => tag)
}

export const constantAdvice = (kind: Project['kind']) => t().guide.constantAdvice[kind]
