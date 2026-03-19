```
sequenceDiagram
    participant W as World
    participant R as Reflex
    participant T as Tactical
    participant P as Periodic Mind
    participant B as Backend

    W->>R: sudden close approach
    R->>T: interrupt current behavior
    T->>R: switch to back-off / alert

    Note over P,B: slower update, not required for instant reaction
    P->>B: summarize recent events
    B-->>P: cautious / curious / social intent
    P->>T: bias next local behavior
```