// What a good dataset looks like, by what the LoRA is meant to learn.
//
// The figures are the ranges the community has settled on for SDXL LoRAs. They are advice, not
// limits: training runs with any number of images.

import { splitTags, type DatasetImage, type Project } from './api'

export interface KindGuide {
  noun: string // "一个角色"
  min: number // below this the result is usually unreliable
  max: number // beyond this more images add little
  tips: string[]
}

export const SMALL_SIDE = 768 // images whose short side is below this are flagged

export const GUIDES: Record<Project['kind'], KindGuide> = {
  character: {
    noun: '一个角色',
    min: 15,
    max: 50,
    tips: [
      '角度和远近都要有：正面、侧面、背面，特写、半身、全身。',
      '换不同的服装、表情、姿势和背景。每张图里都出现的东西，会被当成角色的一部分。',
      '画面里最好只有这一个角色，脸清楚，没有被挡住。',
    ],
  },
  style: {
    noun: '一种画风',
    min: 30,
    max: 150,
    tips: [
      '题材要杂：人物、风景、物件、不同的构图都放一些。只有一种题材，学到的会是题材而不是画风。',
      '所有图片的画风要一致，最好出自同一位作者的同一时期。',
      '同一个角色不要占太多，否则会连角色一起学进去。',
    ],
  },
  concept: {
    noun: '一个概念',
    min: 20,
    max: 60,
    tips: [
      '让它出现在不同的角色、角度和背景里：要学的东西应该是所有图片唯一的共同点。',
      '它在画面里要清楚完整，没有被裁掉或挡住。',
      '远近都要有，不要全是同一种构图。',
    ],
  },
}

// True of every kind of LoRA.
export const COMMON_TIPS = [
  `短边至少 ${SMALL_SIDE} 像素。不用裁成一样的比例，横图竖图都可以。`,
  '不要水印、签名、大段文字和模糊的图，也不要几乎一样的图。',
  '质量比数量重要：一张差图会拉低整体，宁可少放。',
]

export const countRange = (kind: Project['kind']) => `${GUIDES[kind].min}–${GUIDES[kind].max} 张`

export function countAdvice(kind: Project['kind'], count: number): { ok: boolean; text: string } {
  const { noun, min, max } = GUIDES[kind]
  if (count < min) {
    return {
      ok: false,
      text: `${count} 张偏少，学${noun}一般要 ${min} 张以上。图太少容易学不像，或者只会复刻这几张图。`,
    }
  }
  if (count > max) return { ok: true, text: `${count} 张，数量充足。再多帮助不大，多样和质量更重要。` }
  return { ok: true, text: `${count} 张，数量合适。` }
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

export const CONSTANT_ADVICE: Record<Project['kind'], string> = {
  character:
    '如果是角色固有的特征（发色、瞳色），可以把它从标注里删掉，让它归到触发词里。如果不是（衣服、背景），补一些不一样的图，否则它会和角色绑在一起。',
  style: '题材太集中，学到的画风会偏向它。补一些别的题材。',
  concept: '除了要学的概念，其他东西最好有变化，否则会被一起学进去。',
}
