```
ZV_Harbor              type=district   (no confinement — always has something more specific)
│
├── ZV_Bamboo_Boardwalk    type=path       confinement=Semi    surface=Wood
│                          (elevated, open sides but linear — cat feels guided, not free)
│
├── ZV_Houses_Row          type=courtyard  confinement=Open
│   │                      (the between-houses space, open air, human residue everywhere)
│   │
│   ├── ZV_House_Interior  type=building   confinement=Confined   surface=Wood
│   │   (only if cat can enter — if not, skip this entirely)
│   │
│   └── ZV_House_Yard      type=yard       confinement=Open       surface=Stone
│       (the immediate ground around each house — different feel from the row itself)
│
└── ZV_Sea                 type=water      (no confinement)
    │
    └── BP_Boat_03 (moves with prefab)
        ├── ZV_Boat_03     type=vessel     confinement=Semi
        ├── ZV_Deck        type=surface    confinement=Semi    surface=Wood
        └── ZV_Cabin       type=surface    confinement=Confined   surface=Wood
```