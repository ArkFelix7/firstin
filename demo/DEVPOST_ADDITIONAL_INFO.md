# Devpost: Additional info answers

## Sponsor / Special Prizes (select these)

```
Inside and Out: AI for the Built World (CoStar)
Best Use of Deepagents (LangChain)
Build a Messaging Agent using Photon 2.0 (Photon)
Practical AI (Amazon)
```

Do not select the MLH prizes (Gemini, Solana, Tiger Data, Vultr, SpaceXSI, DEV Writing). We didn't use them.

---

## Share feedback about any technology you interacted with at this hackathon (text box)

```
LangChain deepagents: The planner + subagent fan-out and the interrupt_on human-in-the-loop gate were the core of our design and worked well; one interrupt on publish_preplan gave us a real officer sign-off step. We'd like clearer docs on streaming subagent events with subgraphs=True, and on shared virtual-filesystem writes, which caused "parallel file mutation" errors until we moved evidence writes into the tools themselves.

Photon 2.0 (beta): The HTTP API plus Socket.IO events made iMessage approval straightforward, and the officer approving a real plan from an iPhone was our best demo moment. Two things cost us time: a pho_prj_ project ID needs the v2 HTTP API rather than spectrum-ts cloud (which returns a 422), and on shared lines the recipient must text the line first. Both deserve a line in the getting-started guide.

CoStar, Vexcel and Matterport: Having all three layers linked by CoStar's MatterportModelId was excellent and made a three-source agent possible. Vexcel's derived eave and roof height fields came back empty, so we computed height from DSM minus DTM; it agreed with CoStar to within 1% on a 24-story tower. Matterport's automatic room labels are often wrong for commercial space, so we verify them against the panoramas. Census geocoding was 30 to 210 m off; Matterport and CoStar coordinates were reliable.

Anthropic Claude (Sonnet 5.5): Strong vision on aerial obliques and 360° panoramas. Caching answers by image hash made runs reproducible and kept the demo working offline.
```

---

## Share feedback about any technology... (Appears in project gallery: "Select all that apply")

This is a pick-list. Select whichever of these appear in it:

```
LangChain / Deepagents
Photon
CoStar
Matterport
Vexcel
Anthropic / Claude
Vercel
GitHub
Next.js
```

---

## Did you implement a generative AI model or API in your hack this weekend?

```
Yes. FirstIn is built on Anthropic's Claude Sonnet 5.5 through the Anthropic API, orchestrated with LangChain deepagents and LangGraph.

How: A deepagents planner splits each building into NFPA 1660 pre-plan sections and runs three subagents in parallel: a CoStar analyst (building and tenant records), an aerial analyst (Vexcel orthophotos and oblique photos) and an interior analyst (Matterport 360° panoramas). Claude's vision finds roof type, rooftop solar, access walls, staging areas, doors, stairs and storage, and returns bounding boxes that we draw on the source image. A hazard reasoner combines a deterministic rule table with up to three model-added hazards, and a validator enforces that every field cites a source or is marked "Verify on site." A LangGraph interrupt pauses publishing until a fire officer approves, by dashboard or iMessage. Claude also answers crew questions ("where's the exit?") strictly from the approved plan.

Why: The facts a pre-plan needs already exist across three data sources, but nobody has time to read them for every building. Generative AI does the reading and drafting in about 30 seconds, while our design keeps it honest: citations on every line, a second vision pass that checks its own drawings, no inference from a building's age alone, and a human signature before anything reaches a crew.
```

---

## If you are submitting to the Best Use of Gemini API prize category, please provide your Gemini Project Number

```
N/A
```

(We are not submitting to the Gemini prize.)

---

## List of Discord usernames and corresponding names

Fill this in yourself. Format:

```
discord_username1 - Full Name
discord_username2 - Full Name
```
