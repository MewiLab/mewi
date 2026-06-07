# ADR-039: Meaningful Cat Social Communication

## Status

Proposed

## Date

2026-06-07

## Scope

Backend social prompts, `social_proposal`, `intent_arbitrator`,
`intent_effects`, `SocialService`, dialogue payloads returned to Unity,
social-room transcripts, inbox delivery, relationship feedback, and social
memory writes.

Builds on ADR-010, ADR-011, ADR-018, ADR-037, and ADR-038.

## Context

The current backend social-room spine is useful: cats share rooms when they are
co-located, messages are queued in per-cat inboxes, and each cat hears messages
on its own tick. The problem is the speech contract.

The current social proposal prompt asks for a "short cat-like utterance." Given
that instruction, the LLM often returns lines like `mew?`, `mrrp`, or tiny
generic greetings. These are flavorful but not communicative. The cat is
socializing without saying anything another cat can use.

The current social prompt also lacks a strong "what can be communicated" frame.
It tells the model that another cat is nearby and may include relationship mood
or recent room state, but it does not consistently present a concrete
communicative premise: what was heard, what changed, what object/food/route/place
matters, what body need matters, or what the speaker wants the listener to do.
When the model has no premise, it falls back to generic greeting.

Research direction supports a different shape:

- Generative agents become believable through observation, memory, reflection,
  and planning, not free-floating text.
- NPC dialogue systems are stronger when generated dialogue serves
  communicative goals.
- Dialogue acts help control conversation flow and improve response quality.
- Believable agents need motivations and world context; context-free chatter
  does not make a character feel alive.

References:

- Park et al., "Generative Agents: Interactive Simulacra of Human Behavior"
  <https://arxiv.org/abs/2304.03442>
- Strong and Mateas, "Talking with NPCs: Towards Dynamic Generation of Discourse
  Structures" <https://doi.org/10.1609/aiide.v4i1.18682>
- Xu, Wu, and Wu, "Towards Explainable and Controllable Open Domain Dialogue
  Generation with Dialogue Acts" <https://arxiv.org/abs/1807.07255>
- Mateas, "Believable Agents and Interactive Drama"
  <https://www.cs.cmu.edu/afs/cs/project/oz/web/papers/CMU-CS-97-156.html>

## Decision

Cat social speech is no longer a decorative vocalization. It is a small
communication act grounded in the cat's current world, memory, need, and
relationship context.

Adopt these rules:

1. `social_act.say` carries semantic communication.
2. Generic animal noises are not valid standalone `say` values.
3. A cat should speak only when there is a concrete communicative premise.
4. If there is no premise, the social act should be body language or silence.
5. The prompt should expose a compact "communication frame" before asking for a
   `social_act`.
6. The selected act should be represented as a dialogue act: reply, invite,
   check-in, share cue, request, boundary, or greeting-with-content.
7. Target ids must resolve to a real room member before a message is treated as
   directed.

## Communication Frame

Before `social_proposal` asks the LLM to speak, the backend should build a short
speaker-local communication frame:

```jsonc
{
  "heard": [
    {
      "from": "kosto",
      "text": "Sea path smells sharp.",
      "kind": "share_cue",
      "target": "miso"
    }
  ],
  "sayable_cues": [
    {
      "type": "place",
      "id": "Bamboo_Boardwalk_1",
      "line": "This is the current place."
    },
    {
      "type": "body",
      "line": "Energy is low, so rest or stillness fits."
    },
    {
      "type": "food",
      "id": "a fat silver mackerel",
      "line": "Food smell was recently important."
    },
    {
      "type": "route",
      "id": "Sea_1",
      "line": "The sea route is reachable but risky."
    }
  ],
  "relationship": [
    {
      "peer_id": "kosto",
      "line": "Trust is still forming; keep the signal simple."
    }
  ]
}
```

This frame should be built from existing state:

- `social_context.delivered_inbox`
- `social_context.room.recent_transcript`
- `social_context.relationships`
- `structured_context.place`
- `structured_context.body`
- `structured_context.semantic_context`
- `memory_state.recent`
- `intent_affordances.targets`

The frame is not a new source of truth. It is a prompt-facing distillation of
what is already present.

## Social Act Contract

The social proposal output remains JSON, but the meaning of `say` changes:

```jsonc
{
  "intent": "SOCIALIZE",
  "target_id": "kosto_cat",
  "mood": "tired but receptive",
  "style": "settles low, ears soft",
  "social_act": {
    "kind": "invite",
    "say": "Sit here; the boardwalk is warm.",
    "tone": "soft",
    "expects_reply": true
  },
  "reasoning": "Kosto is nearby, Miso has low energy, and the warm boardwalk is a concrete shared cue."
}
```

Allowed `kind` values:

| Kind | Use |
|---|---|
| `reply` | Answer a delivered inbox line or recent direct transcript line. |
| `invite` | Ask the target to join, follow, inspect, rest, or share a place/object. |
| `check_in` | Low-pressure social contact, usually about a body/mood cue. |
| `share_cue` | Point out food, route, sound, smell, object, or place information. |
| `request` | Ask for space, help, following, waiting, or attention. |
| `boundary` | Communicate avoidance, fear, guarding food, or need for distance. |
| `greeting` | Only valid when paired with a concrete cue, not standalone "hello". |
| `message` | Fallback for concrete speech that does not fit the above. |

Invalid standalone `say` values:

- `mew?`
- `mrrp`
- `chirp`
- `hi`
- `hello`
- `come here`
- any repeated generic line already in the recent transcript

Valid examples:

- `Fish smell is near the boxes.`
- `Sit here; the boardwalk is warm.`
- `Sea path feels sharp. Stay back.`
- `You heard that too?`
- `I am tired. Stay close.`
- `Food first. Then I will move.`

The text should still be short enough for a speech bubble. The difference is
that it now carries an in-world meaning.

## Prompt Contract

The social proposal prompt should include:

- "social_act.say is communication, not decoration."
- "Do not use generic animal noises as standalone speech."
- "If there is no concrete message, leave `say` empty."
- "Prefer replying to the latest delivered inbox item over starting a new topic."
- "Use food/place/route/body/relationship cues when they matter."
- "Do not invent a cue, target, utterance, or reaction."
- "Never decide how the listener responds."

The prompt should avoid phrases like:

- "short cat-like utterance"
- "visible chirp" as the main output goal
- "small greeting" without requiring content

Cat flavor belongs in `tone`, `style`, animation, audio, or future optional
fields, not as the whole semantic message.

## Target Resolution

Social targets currently may use different ids across systems:

- Unity/entity affordance id: `kosto_cat`
- Backend creature/room id: `kosto`
- Possible alternate creature id style: `cat_kosto`

The social router should resolve these aliases before delivery:

```text
kosto_cat -> kosto
cat_kosto -> kosto
kosto -> kosto
```

If a target cannot resolve to a current room member, the line is group-facing
only if the speaker explicitly chose an empty target. Otherwise the publish step
should mark the directed target unresolved for debugging and avoid claiming a
direct reply was requested.

## Anti-Loop Rules

To prevent meaningless social loops:

1. Do not publish a `say` value that is equivalent to one of the speaker's last
   three transcript lines.
2. If the latest delivered message expects a reply and the cat chooses
   `SOCIALIZE` toward that speaker, prefer `kind: reply`.
3. If the cat chooses another intent, resolve the bid as ignored,
   acknowledged, or deferred.
4. A room may produce body-language contact without speech.
5. Silence is valid when no new information exists.

## Implementation Plan

Phase 1: Prompt and frame

- Replace "short cat-like utterance" with "grounded communication act."
- Add communication-frame lines to `social_proposal`.
- Add tests that the generated prompt includes communication rules and concrete
  cues from inbox/place/body/sensory state.

Phase 2: Router robustness

- Add room-member alias resolution in `SocialService.publish_turn`.
- Add tests for `kosto_cat` routing to room member `kosto`.
- Ensure `wake_targets` uses resolved room ids.

Phase 3: Memory and evaluation

- Store heard/spoken communication kind alongside text when available.
- Add a small regression fixture using a real prompt like the Miso/Kosto case.
- Add a checker that rejects generic `say` values when concrete cues exist.

## Consequences

Positive:

- Social lines become useful state, not just cute texture.
- Cats can ask, warn, invite, reply, and express needs.
- Memory consolidation has real social content to carry forward.
- Relationship changes become easier to explain because the interaction has a
  semantic act.

Tradeoffs:

- Some lines will sound less like literal cat noises and more like translated
  cat intent. That is acceptable because the simulation needs communication
  first; audio/animation can carry the meow layer.
- The prompt will be slightly longer.
- The router needs alias handling so semantic target ids and room member ids do
  not split the social system.

Rejected alternatives:

- Keep `mew/mrrp` speech and infer meaning elsewhere. This hides the important
  information from memory and from the receiving cat.
- Add a separate dialogue LLM immediately. The existing social proposal path can
  carry this if the prompt and frame are fixed.
- Let the moderator write better lines for both cats. ADR-038 chooses subjective
  cat authorship; each cat should only speak for itself.

## Review Questions

1. Should `dialogue.text` display translated intent directly, or should Unity
   eventually render separate `vocalization` and `meaning` fields?
2. Should generic animal sounds be fully rejected, or allowed only when
   `say` is empty and `style`/audio carries the sound?
3. Should unresolved directed targets fail closed, or degrade to group-facing
   speech?
