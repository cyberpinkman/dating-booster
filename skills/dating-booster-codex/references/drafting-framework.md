# Chinese Dating Reply Drafting Framework

This framework is for host agents drafting Chinese dating-app replies. It is not
a hard template. Use it to think more like a person in a private chat.

## Read The Situation

Before drafting, write a one-sentence `situation_read`:

- 对方投入度: high, medium, low, or unknown.
- 最后一句类型: question, short acknowledgement, tease, logistics, silence reset.
- 当前阻力: user over-sent, thread is dry, topic is too generic, distance, timing.
- 用户是否已经连续输出过多: if yes, keep the next reply lighter and shorter.

First identify the `turn boundary`: `latest_inbound_messages` means match
messages after the user's latest outbound. Draft from those messages as the
primary hook. Old visible messages are background only; do not answer a stale
bubble just because it is still visible on screen.

If `latest_inbound_messages` is empty or the turn boundary is unclear, do not
draft as if the latest visible match bubble is fresh. Re-observe, ask the user
for the current live message, or use an explicit reset/nudge workflow.

When a `goal_plan` or planner recommendation exists, draft toward its
`next_milestone`. Treat `topic_saturation`, `soft_invite_probe`, and
`bridge_topic` as strategy constraints: if a topic is saturated, bridge or reset
instead of continuing an interview; if soft invite is not allowed, do not push
for meeting. The draft's conversation move should match the planner move unless
the rationale explicitly explains an equivalent move.

For low-investment replies like "嗯嗯", "没有", "挺不错的", do not add a long
explanation. Bridge from the last message and offer one easy opening.

Before writing, choose one of five directions: `给/问/接/转/停`.

- `给`: share a small true or allowed-simulated user detail.
- `问`: ask one specific unknown detail only when the match has enough energy.
- `接`: answer, riff, or react to the latest message.
- `转`: bridge away from a saturated topic.
- `停`: wait or slow down when the thread is too one-sided.

Do not default to questions. If the user has asked multiple questions in a row,
or the match has given two low-investment replies, switch to giving a small
self-disclosure, lightly riffing, or waiting.

## Choose The Conversation Move

Use one `conversation_move`:

- `answer_or_riff`:对方已经提问、吐槽或惊讶时，先回答或接梗。
- `take_the_lead`:对方把选择权交给你时，接过来给一个轻量具体决定。
- `bridge_topic`:接住最后一句，再轻轻转到下一个点。
- `deepen_current`:挖 profile 标签背后的未知细节。
- `light_self_disclosure`:给一点自己的信息，但不抢话。
- `reciprocal_disclosure`:对方分享了自己时，先给一个对应的自己。
- `low_investment_repair`:对方短回或低投入时，用轻自曝/轻接梗修复，不继续采访。
- `reset_thread`:前面聊干了，换一个轻题。
- `soft_invite_probe`:只有对方投入度足够时，轻试探线下可能性。
- `slow_down_wait`:低投入修复后仍无扩展，暂缓推进。

For the first version, prefer `bridge_topic` or `deepen_current` when the
match is replying briefly.

Use `answer_or_riff` when the match has already given you an active opening.
Question is optional: the reply can simply answer, agree, tease, or add a funny
take. Do not force a question just to keep the thread alive.

Use `take_the_lead` when the match says things like "你定", "你安排",
"随你", or "听你的". This is a handoff, not an invitation to keep asking.
不要继续反问. Pick a small, low-pressure decision that fits the thread and
their profile boundaries.

Use `low_investment_repair` when the user has been asking and the match is only
answering. The reply should usually contain zero direct questions. Give one
small user-side detail, a light reaction, or a soft bridge. If that repair does
not produce new energy, choose `slow_down_wait` instead of pushing again.

Use `light_self_disclosure` or `reciprocal_disclosure` to make the conversation
two-sided. Pick material from the user disclosure profile when possible. If the
profile allows `free_simulation_soft`, the agent may simulate soft persona,
attitude, or low-risk生活感, but must not invent hard facts such as city,
education, work, age, family status, or past commitments.
If the profile uses `material_only`, every disclosure draft must set
`disclosure_source: "user_material"` and include the exact
`used_user_material_ids`. If the profile uses `user_confirmed_only`, stop for
user confirmation before sending any self-disclosure.

## Choose The Hook

Prefer hooks that can reveal unknown details:

- Known tag: likes movies. Better unknown detail: what type of movie, recent
  favorite, cinema vs home, comedy vs suspense.
- Known tag: night owl. Better unknown detail: what they do late at night, what
  they listen to, whether they are out or at home.
- Known tag: coffee. Better unknown detail: bitter coffee or milk coffee,
  favorite shop vibe, coffee for survival or taste.

Avoid asking the match to choose among tags they already wrote. That often gets
"都行" or "看情况".

Prefer lifestyle, interests, scenes, and shared rhythm before work. A job label
such as "运营" is not enough reason to lead with work style. Use work only when
the match explicitly mentions work, shows strong work/事业投入, asks about work,
or has no better lifestyle/interest hook available.

## Shape The Reply

- 一句为主，最多两句。
- If one reply has two jobs, such as 承接上一句 and opening a new hook, use
  `message_sequence` with two or three short bubbles instead of one dense line.
- Managed live-send continuity for `message_sequence` is 20 seconds per bubble
  from before the first send attempt; if the window expires after a partial
  send, do not send the remaining bubbles later without re-observing and
  replanning.
- Do not mechanically split every comma or period. Each bubble needs a clear
  role: acknowledge, add a concrete handle, or land the push. The final bubble
  should usually carry the conversational push.
- One question at most; zero questions is often better when the match already asked something.
- If the match asked a question or showed surprise, answer or riff before adding a new hook.
- Do not force a question when a natural reaction would be stronger.
- If the match delegates a choice, make one concrete choice instead of bouncing the decision back.
- Avoid survey-style A/B wording. Use A/B only when the options are visible,
  concrete, natural, and the choice itself has conversational payoff.
- Never make an already-confirmed fact one side of an A/B choice. If the match
  already said she is slow to warm up, "聊天慢慢熟还是..." is not a real option.
- When testing one guess, prefer a yes/no-style hypothesis or light statement:
  "你会是见面更放松一点的那种吗" reads more human than "你是 A 还是 B".
- Use one label at most. "夜猫子" is enough; "ESFP 夜猫子" usually sounds like tag stacking.
- Prefer concrete words over abstract planning words.
- If the previous user sent many messages, do not send another multi-line bundle.
- If the previous user asked multiple questions, avoid another direct question.
- For low-investment repair, prefer one short self-disclosure or riff with zero questions.
- Include `question_count` or `reply_shape` in draft JSON when the thread is in
  low-investment repair; under high question debt, any direct question is
  blocked even if the move is `bridge_topic`.
- Self-disclosure must help the current milestone:生活感, humor, shared rhythm,
  comfort, or a softer path toward meeting.

## Worked Example: A Case

Situation:

- Match has profile hooks: movies, coffee, singing, music, comedy, night owl.
- Latest message: "挺不错的".
- User has already sent several messages and should not over-explain.

Weak drafts:

- "你平时放松更偏咖啡、电影还是听歌？"
- "下次我得听听 ESFP 夜猫子的放松路线..."

Better direction:

- "还行，夜风加点酒确实挺舒服😂 你这种夜猫子晚上不睡觉的时候一般听谁的歌？"
- "哈哈是挺舒服。你不是也爱电影吗，ESFP 一般会喜欢哪种片？"
- "主要是夜风不错。你平常是更爱看电影，还是出去听歌？"

Why this works:

- It connects to the current thread.
- It asks for an unknown detail beneath a known profile tag.
- It avoids three-option interview wording.
- It keeps the voice casual and short.

## Worked Example: News Riff Case

Situation:

- Match profile hooks include low laugh threshold, travel, coffee, food, fitness,
  liking winter but disliking winter cold, and wanting to live more freely.
- Latest message: "没细看，怎么会这么精彩啊 / 哈哈哈哈咋想的啊".
- The match is actively reacting and asking a question. The user has already
  explained the news setup, so another long explanation would drag.

Weak drafts:

- "你觉得他为什么会坐两个小时公交去酒吧？"
- "哈哈你是不是也喜欢这种离谱新闻？"
- "从心理动机来看，他可能是长期压抑后的释放。"

Better direction:

- "我也想知道他咋想的，感觉是那种“来都来了”精神突然烧起来了哈哈哈"
- "可能当时脑子里只有一句：都到这了，不喝亏了哈哈哈"
- "这哥们儿行动力有点离谱，换我坐到一半就开始后悔了哈哈哈"

Why this works:

- It answers or riffs on the match's question instead of forcing another question.
- It stays on the live thread rather than jumping back to profile tags.
- It avoids analysis voice and keeps the reply short enough for a playful chat.

## Worked Example: Reward Delegation Case

Situation:

- Match profile hooks include pure love, long-term partner, gifts as love
  language, Japanese food, concerts, yoga, no alcohol, no smoking, dog preference,
  INFP, and best communication in person.
- User has been asking what reward she wants after she called him cute.
- Latest message: "你定".

Weak drafts:

- "那你想要什么奖励？"
- "你猜我会给你什么奖励？"
- "那奖励你一个亲亲。"

Better direction:

- "那我定了，奖励你一个点菜权，下次日料你挑一家"
- "那我定了，奖励你一个愿望额度，不过不能太离谱"
- "那奖励你继续发现我的优点，发现得准还有加餐"

Why this works:

- It accepts the handoff instead of asking her to decide again.
- It keeps the reward playful and specific without becoming sexually forward.
- It uses profile-compatible hooks: Japanese food, gifts, pure-love pace, and
  long-term/low-pressure intent.

## Worked Example: Slow-Warm Bridge

Situation:

- Both sides have acknowledged 慢热.
- The next move should make the thread more meetable, not explain what 慢热
  means.

Weak draft:

- "你是聊天慢慢熟，还是见到人之后反而更容易放松"

Issue: the first option only restates the confirmed fact. The A/B shape exposes
planner logic and makes the match choose between a known fact and a new guess.

Better direction:

- "那慢热同盟先成立"
- "不过我生活中还是比较能聊的"
- "你会是见面更放松一点的那种吗哈哈"

Why this works:

- It acknowledges the shared trait without explaining it.
- It adds user-side energy.
- It tests one useful meet-path hypothesis in a human yes/no shape.

## Worked Example: Lifestyle Before Work

Situation:

- Match profile says "运营" plus lifestyle hooks like 露营, 咖啡, 电影.
- The match has not made work a live topic.

Weak draft:

- "你平时更像救火队长，还是提前把坑都填好的那种"

Issue: it turns a job label into a work-style interview and uses stiff A/B
wording. In a dating context, work should not outrank available lifestyle hooks
unless the match made work salient.

Better direction:

- Bridge into 露营、咖啡、电影, or another concrete生活场景.
- If work later becomes salient, use one concrete work-adjacent observation
  rather than an interview-style work personality choice.
