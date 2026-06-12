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
- 如果用了 `message_sequence`, 每条气泡是否都有独立作用，而不是机械按逗号/句号切开?
- 最后一条气泡有没有承担推进、落点或自然交还话题?
- 如果对方已经提问、吐槽或惊讶，草稿是在接话，还是为了续聊而强行提问?
- 如果对方说 "你定"/"你安排"/"听你的"，草稿是在接过选择权，还是继续反问?
- Does it ask about an unknown detail, or only repeat an 已知标签 from the profile?
- Could the match easily answer only "都行" or "看情况"? If yes, ask something more specific.
- Does it use 抽象词 or AI-sounding nouns such as "路线", "放松方式", or "选择倾向"?
- Does it use logic-comparison wording like "偏 A 还是 B" when a person would say "喜欢 A 还是 B"?
- Does it use an unnatural multi-option question such as "A 还是 B 还是 C"?
- Does it make an already-confirmed fact one side of an A/B choice?
- If the draft only needs to test one guess, would a yes/no-style question sound more human than "A 还是 B"?
- Is it leading with work when lifestyle or interest hooks are available and the match has not made work salient?
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

Bad:

> 你觉得他为什么会坐两个小时公交去酒吧？

Issue: the match already asked "咋想的啊"; returning the same question feels
like forced interviewing instead of answering or riffing.

Better:

> 我也想知道他咋想的，感觉是那种“来都来了”精神突然烧起来了哈哈哈

Bad:

> 那你想要什么奖励？

Issue: the match has already delegated the choice with "你定"; asking again
keeps bouncing the decision back.

Better:

> 那我定了，奖励你一个点菜权，下次日料你挑一家

Bad:

> 你是聊天慢慢熟，还是见到人之后反而更容易放松

Issue: "聊天慢慢熟" only restates 慢热 after both sides have already confirmed it.
The A/B form makes the draft look planned rather than spoken.

Better:

> 你会是见面更放松一点的那种吗哈哈

Bad:

> 你平时更像救火队长，还是提前把坑都填好的那种

Issue: this turns a job label into a work-style interview and uses stiff A/B
wording. Work is not the best first hook when the profile also has normal
dating-context hooks like camping, coffee, movies, music, pets, or food.

Better:

> 你露营会是那种到地方就开始放空的人吗哈哈
