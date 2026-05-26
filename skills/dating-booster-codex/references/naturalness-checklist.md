# Chinese Naturalness Checklist

Use this before showing a Chinese draft. This is a human-context check, not a
mechanical banned-word list.

## Output Policy

This checklist is an internal QA tool, not a default user-facing output format.
Use it to revise the draft silently. Do not show checklist results, validation
notes, or per-item reasoning unless the user explicitly asks for explanation,
critique, review, or debug output.

## Checklist

- 真人会不会这么打字: Would a normal Chinese dating-app user send this exact sentence?
- Is there one clear move, or did the draft pack too many ideas into one line?
- Does it ask about an unknown detail, or only repeat an 已知标签 from the profile?
- Could the match easily answer only "都行" or "看情况"? If yes, ask something more specific.
- Does it use 抽象词 or AI-sounding nouns such as "路线", "放松方式", or "选择倾向"?
- Does it use logic-comparison wording like "偏 A 还是 B" when a person would say "喜欢 A 还是 B"?
- Does it use an unnatural multi-option question such as "A 还是 B 还是 C"?
- Does it have 标签堆叠, such as "ESFP 夜猫子", when one label would be enough?
- Is it too polished, balanced, or explanatory for the user's previous style?

## Bad To Better

Bad:

> 你平时放松更偏咖啡、电影还是听歌？

Issue: "偏" exposes logical comparison; three interests are treated like a survey.

Better:

> 你平常是更爱看电影，还是出去听歌？

Better if the goal is to deepen:

> 你不是也爱电影吗，ESFP 一般会喜欢哪种片？

Bad:

> 下次我得听听 ESFP 夜猫子的放松路线：咖啡、电影、听歌你会先选哪个？

Issue: tag stacking, "放松路线" is not natural Chinese private-chat wording, and the
three-option structure feels like AI.

Better:

> 下次我得听听夜猫子晚上不睡觉的时候都听谁的歌了

Bad:

> 你喜欢咖啡还是电影还是唱歌？

Issue: A/B/C "还是" chain is rare in casual Chinese unless the user is choosing
from visible concrete options.

Better:

> 你平常更爱看电影还是唱歌？

Better if the tag is already known:

> 你唱歌一般唱哪种，KTV 那种还是自己听歌跟着哼？
