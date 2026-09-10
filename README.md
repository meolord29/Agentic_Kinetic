<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/d6d06622-7e64-43b7-a1f5-b630129627dc" />

Address: 3/F, Core A, 3, Cyberport, 100 Cyberport Rd, Pok Fu Lam, Hong Kong Island, Hong Kong. Bus routes 30X, 42C, 73, 73P, 107P, or 970. Minibus routes 10, 10P, 58, 58M, 69, 69A, or 69X serve the venue.
From Tai Wai ~1.5hrs:
1. Take East Rail Line to Admiralty then Island Line to HKU or Kennedy Town MTR stations:
- Via HKU Station (Island Line): Take Exit A and transfer to Citybus 30X or 970 directly to the campus. 
- Via Kennedy Town Station (Island Line): Take Exit A and catch Green Minibus 58.

Buses arrive directly at the Cyberport Public Transport Interchange: 
From Central: Bus 30X
From Mong Kok / Kowloon: Bus 970
From North Point: Bus 42C
From Causeway Bay: Green Minibus 10, 69X, or 10P
From Stanley: Bus 73

Taxi/ride-hail app: input the address as 100 Cyberport Road. Drivers can enter via the Car Park 3 Entrance, which offers direct lift access into Cyberport 3.

Core A's Location: Core A sits at the far southern end of the Cyberport 3 block, closest to Cyberport 1 and Cyberport 2. [1] (https://www.cyberport.hk/en/about_us/cyberport_campus/)
Cyberport 3 is the longest, continuous building on the campus. It is divided into six interconnected vertical blocks (labeled Core A through Core F)
The Entryway: If you are dropped off at the main Car Park 3 Entrance, you will be right by the center blocks (C/D). To reach Core A, walk past Core B toward the south end of the main Level 1 indoor concourse.
If you are navigating using a GPS app, search for "The Arcade at Cyberport" or "Le Méridien Hong Kong, Cyberport". Core A is directly adjacent to these landmarks, sharing the same waterfront plaza layout.

The Arcade at Cyberport Google Maps link: https://maps.app.goo.gl/RtZ9fSBShw8FXdPb9

Starts at 10, but they don't have enough space so we should aim to get there early. I can go earlier to reserve our spot since I'm closer.
I'll bring an extension cable, charger, cables, banana bread.


From the Portal, this is exactly everything we need to submit:

A. DESCRIPTION [JUNE] (Markdown or plain text is acceptable)
Describe your project focusing on how it delivers a functional agent within its chosen environment. Explain the problem it solves and how the agent’s presence in that specific context makes it meaningfully more useful than a standalone chatbot. Highlight the innovation and how the environment shapes the agent’s core workflow.
Detail the technical execution, including specific technologies, frameworks, and libraries used. Explain how the agent provides clear value and an intuitive, effective experience for users. Your description must be at least 25 words long (longer is welcome) to help judges understand your project’s alignment with all criteria.

--> Draft (not yet reviewed/rewritten & we should check if we can insert graphics): https://docs.google.com/document/d/11ASTIhSkijvsFJ0LT0wCAxCvcbre9J-0jRI006_mZQI/edit?tab=t.0#heading=h.squ8onl9p2oc


B. TOOLS (just click this last): What of the following were used to create your product or were particularly helpful during the hackathon? 
[IVAN: Track these and describe them as you go.]

C. VIDEO [JUNE]:  Optional: 2-minute YouTube or Loom video link. Helps judges understand your project and appears on winners page. Video creation guide »
Important: please limit your video to 2 minutes. Longer videos may deduct points.
YouTube must be Unlisted/Public. Loom must be shareable.
--> Draft (not yet reviewed): https://docs.google.com/document/d/1vgqtbevU2osvBTpvFypzk0X0MrnOupzq5YbtKSz2r7c/edit?tab=t.0#heading=h.d98uxddf71a3


D. TEAM CONTRIBUTIONS: Describe their role on the team and their contributions (tools used, specific components built, etc.)
Ivan:
June:


E. ADDITIONAL LINKS:
Provide other project related links here such as GitHub repositories, project website, etc. This will be showcased on the winners page and entries list and are helpful for judging. 

1. https://github.com/meolord29/Agentic_Kinetic. Title: Agentic_Kinetic. Description: TBD
2. https:// Title & Description - Should we do a project website/Visual imagery is good? --> Draft (not yet reviewed/rewritten): https://docs.google.com/document/d/1uHZ9Y7Yjq9hVPHIO1eZ2TaoMmesDhNG8s4CyxvZny_I/edit?tab=t.0#heading=h.jwc35sloqfuz
3. (same as above) --> Not sure about this powerpoint unless it's very visual but we may want to do a video: https://docs.google.com/presentation/d/1mOu_S_HuGJ7VmLbSBwwPBFuU9zt0-vck8D6lbTyohi4/edit?slide=id.ak_s12#slide=id.ak_s12

Link options for a website:
1. Add content to this repo = simplest.  We could try to render images of the app for the patient & the doctor with example questions to show the UX.
2. A one-page site with the story, video, screenshots and links — no live agent. Host on Google Cloud Run?
3. Optional: Actual doctor dashboard, built with CopilotKit and hosted on Google Cloud Run, with a short intro section (story, video, links). Best evidence for 'working agent' and uses two sponsors for real but this takes extra time.

Visual ideas:
Here is a structured, highly scannable layout for a presentation slide or website graphic. It visualizes the continuous feedback loop between the patient's gamified routine and the clinician's automated dashboard.

========================================================================================
             THE AUTONOMOUS FEEDBACK LOOP: FROM HOME LOGISTICS TO CLINICAL ACTION
========================================================================================

    [ STEP 1: PATIENT CHANNEL ]                [ STEP 2: BACKEND AGENT ]
    +---------------------------+              +---------------------------+

    |   DAILY GAMIFIED LOG      |              |   REAL-TIME CALIBRATION   |
    |  "What time did you take  | -----------> | Calculates daily wave     | (<----and/or does Exa research)
    |   your pill? Any stomach  |              | Flags risks via strict    |
    |   upsets today?"          |              | clinical rules.           |
    +---------------------------+              +---------------------------+
                  ^                                          |

                  | [4. NEW ROUTINE]                         | [3. SMART ALERT]
                  |                                          v
    +---------------------------+              +---------------------------+

    |    INTERACTION RESET      |              |    CLINICAL DASHBOARD     |
    |  Patient gets a targeted  | <----------- | Doctor reviews data and   |
    |  question to capture a    |              | sends the agent to gather |
    |  new dynamic variable.    |              | highly specific data.     |
    +---------------------------+              +---------------------------+
    [ STEP 4: CLOSING THE LOOP ]               [ STEP 3: CLINICIAN ACTIONS ]
========================================================================================

1: The Patient Experience (Gamified & Low Friction)Visual Element: A sleek smartphone interface mockup displaying a crisp, encouraging gauge chart.The Focus: Progress and Data Certainty.Key Text Copy:Headline: The "Certainty Score" Dashboard.The Mechanic: The app never judges the patient's compliance or scores their character. Instead, it turns data collection into a cooperative "power-up." Every factual answer regarding meal times, stomach health, or unexpected prescriptions pushes the Predictive Certainty Score closer to 100%.The Ultimate Prize: Maintaining a high accuracy score stabilizes the medical twin, unlocking a real-world reward: the software safely suggests fewer painful clinic visits and fewer needle sticks to the doctor. The patient wins back their personal time.

2: The Autonomous Agent (The Processing Engine)Visual Element: An abstract central graphic showing raw user data instantly morphing into a mathematically smooth pharmacokinetic (PK) daily wave curve.The Focus: Continuous Tracking Between Visits.Key Text Copy:Headline: The Real-Time Analytical Twin.The Mechanic: While the patient goes about their day, the agent runs their logs through transparent Bayesian calibration. It shifts their profile away from a static population average and customizes it to their live physiology.The Guardrail: If an event occurs—like a sudden bout of diarrhea or an interacting antibiotic—the system immediately predicts an incoming toxic spike or a drop into organ rejection. It instantly bypasses the standard, delayed monthly blood-draw schedule and alerts the medical team.

3: The Clinician Dashboard (Review & Command)Visual Element: A clean desktop software interface showing an active, high-priority alert box with direct action buttons.The Focus: Total Clinical Control & Zero Administration Waste.Key Text Copy:Headline: High-Utility Triage for the Transplant Team.The Mechanic: The Transplant Coordinator or Nephrologist sees exactly why the patient is at risk, backed by clear biological reasoning (e.g., "Intestinal inflammation destroying the CYP3A4 gut checkpoint").The One-Click Directive: The doctor doesn't waste hours chasing the patient via phone tag. Instead, they hit [Authorize Target Survey]. This commands the autonomous agent to immediately ping the patient's phone with high-utility, factual questions (e.g., tracking the exact time a new interacting drug was swallowed) to gather the data required for a same-day dosing adjustment.

4. The Trigger Event: A patient's primary care doctor or a local dentist prescribes a new medication (like an antibiotic or antifungal) without realizing it clashes with their transplant regimen. The patient logs this new pill in the app, and the clinician triggers a Targeted Medication Shift Survey from their dashboard to map the threat.

- The Agent Asks:"Let's map your new medication to keep your kidney safe, Elena. What time did you take the new pill today, and did you take it at the exact same time as your morning transplant pill?"
- The Biological Logic: Many common medications directly block or accelerate the CYP3A4/5 enzymes in the gut wall and liver. If the new pill is swallowed at the exact same moment as the tacrolimus, they physically collide at the first checkpoint, causing an immediate, erratic spike or crash in absorption.
- The Insight for the Doctor: The software overlays the new drug’s absorption timeline against the patient's existing tacrolimus PK curve. This tells the Nephrologist if they need to separate the dosing schedules (e.g., morning vs. evening) to stop them from crashing into each other at the gut wall.

5. The Direct Blocker: Antifungals / Antibiotics
- What the Agent Asks:"Can you select the exact name or color of the new bottle from this list? If it's a cream, liquid, or pill, let us know." (The app displays a visual list of high-risk drugs like fluconazole, erythromycin, or Paxlovid).
- The Biological Logic: Certain drugs are powerful enzyme inhibitors. They put the body's security checkpoint guards entirely to sleep. Without those enzymes working, the body cannot break down the transplant drug, causing the next dose of tacrolimus to flood the blood at a 2x to 5x higher concentration, causing direct kidney toxicity.
- The Insight for the Doctor: The agent instantly calculates the strength of the inhibitor based on published medical literature. It warns the doctor: "This specific drug combination will likely double the patient's exposure within 48 hours. Suggest reducing the tacrolimus dose by 50% immediately while they take this course."

6. The Direct Accelerator: Corticosteroids / Seizure Meds
- What the Agent Asks:"Is this a new steroid pill (like prednisone) or a medication for seizures or nerve pain?"
- The Biological Logic: These drugs are enzyme inducers. They act like a shot of adrenaline for the body's security checkpoint guards. They cause the liver to shred tacrolimus at lightning speed. The drug is wiped out before it can protect the organ, causing a massive plunge in blood levels that opens the door for silent organ rejection.
- The Insight for the Doctor: The agent flags a severe under-exposure warning. It alerts the Nephrologist: "Clearance rate is projected to increase by 40%. The patient is at risk of falling below the safe therapeutic window. Suggest an immediate, temporary dose increase."

7. The Exit Gate Block: Kidney Competitors (NSAIDs)
- What the Agent Asks:"Did anyone recommend a common painkiller like ibuprofen (Advil/Motrin) or naproxen (Aleve) for an ache or fever?"
- The Biological Logic: Over-the-counter NSAIDs directly constrict the blood vessels feeding the kidney filtering units. Because tacrolimus already does this at high doses, combining the two creates a compound chokehold on the organ. It cuts off blood flow so severely that it can cause sudden, acute kidney injury.
- The Insight for the Doctor: This triggers an absolute red-flag alert. The agent informs the doctor: "Patient has taken an NSAID. High risk of immediate blood vessel constriction and a spike in creatinine levels." The doctor can instantly send a pre-authored message through the agent telling the patient: "Stop taking the ibuprofen immediately. Switch to Tylenol, which is safe for your kidney."

How It Appears on the Clinician Dashboard
Instead of a generic notification saying "Elena started a new drug," the agent synthesizes the answers to these four questions into a clean, actionable summary:
+-----------------------------------------------------------------------------------+

| ⚠️ INTERACTION ALERT: MEDICATION SHIFT SURVEY COMPLETE                             |
| Patient: Elena Cruz | New Drug: Fluconazole (Antifungal)                          |
+-----------------------------------------------------------------------------------+

| LOGISTICS: Taken at 08:00 AM alongside Tacrolimus. Empty stomach.                 |
| BIOLOGICAL THREAT: Strong CYP3A4 inhibitor. Checkpoint shutdown imminent.         |
| PROJECTED IMPACT: Tacrolimus clearance will drop by ~60%. AUC will spike to toxic  |
|                   levels within 24-48 hours, risking severe kidney scarring.      |
|                                                                                   |
| PROPOSED ACTION:                                                                  |
| [1] Click below to text Elena: "Separate pills by 4 hours; reduce dose to 1mg."   |
| [2] Order a remote 4-point finger-prick test for Friday morning to verify.        |
|                                                                                   |
|  [ APPROVE ACTION ]    [ EDIT INSTRUCTIONS ]    [ DISMISS ]                       |
+-----------------------------------------------------------------------------------+

Long-Term Patient Engagement Strategy

A chronic patient faces a 20+ year journey. Traditional app push notifications lose their effectiveness within weeks. To sustain participation indefinitely, the agent utilizes a Zero-Friction Behavioral Framework modeled on behavioral economics:
- Frictionless Micro-Logging (Under 10 Seconds): The app never forces a patient to navigate deep menus. Every morning, the check-in appears as a rich, interactive notification directly on their lock screen. One tap registers the time; one swipe confirms food status. If everything is normal, the interaction ends in under 10 seconds.
- The "Habit Loop" Integration: The app anchors itself to a physical trigger the patient already does every single day: swallowing their pill. The lock-screen check-in acts as the digital mirror to their physical routine.
- Predictive Notification Shifting: If the patient's data twin shows they always take their medicine at exactly 8:05 AM, the agent learns this rhythm. It automatically adjusts its check-in alert to 8:10 AM. It never bugs the patient early, preventing "alarm fatigue."
- The Autonomy Payoff: As established in the gamification layout, the system explicitly visualizes how high data accuracy directly buys back their personal freedom. The message is clear: "Your data is perfect, your kidney map is totally stable, so we have extended your wellness streak. You don't need a blood draw or a clinic visit for another 60 days."

The Financial Projections (Clinic Savings Framework) - use a McKinsey consulting slide layout
For healthcare executives, your software is an administrative and financial relief valve. Let's calculate the exact return on investment (ROI) for a standard regional transplant clinic managing 500 active kidney patients.
1. Reclaiming Clinician Time (Administrative ROI)Currently, a transplant coordinator (specialized RN) spends hours playing phone tag to trace missed labs, track down patients, or request missing information.The Current Burden: On average, a coordinator spends 1.5 hours per patient per month on routine administrative tracking and data collection. Across 500 patients, that is 750 hours a month of pure administrative manual labor.The Agent Impact: The agent automates 100% of the routine daily logs, interaction surveys, and reminders. It only flags the 5% of patients in active distress. This drops administrative time to just 10 minutes per patient per month.The Math: 500 patients × 10 minutes = 83 hours a month.The Cash Saved: You compress the workload from 750 hours down to 83 hours, effectively reclaiming 667 hours of nursing capacity per month. At an average specialized nurse cost of $60/hour, this saves a single clinic $40,020 a month—or over $480,000 every single year in administrative waste.
2. Avoiding Re-Hospitalizations (Clinical Cost Savings)As noted in the scientific backgrounder, dialysis patients are hospitalized an average of twice a year at a massive cost to the system.The Current Threat: In a standard pool of 500 kidney transplant recipients, roughly 4% to 5% lose their organ annually due to unmonitored drug variability and non-adherence. That means 22 patients per year experience graft failure and return to chronic dialysis.The Cost of Failure: Losing 22 patients to dialysis costs the system $2.1 Million annually in direct dialysis bills, plus an estimated $500,000 in emergency hospitalization and bed capacity.The Agent Impact: By catching the "three-year warning signal" in the data early, stabilizing exposure curves, and catching silent rejections, the agent reduces the graft failure rate by a conservative 40%.The Savings: The clinic prevents 9 out of those 22 failures every year. This preserves 9 human lives outside of a dialysis chair and directly saves the healthcare system over $1.1 Million annually in avoided care costs.

+-----------------------------------------------------------------------------------+

|               REGIONAL TRANSPLANT CLINIC ROI SHEET (BASIS: 500 RECIPIENTS)        |
+-----------------------------------------------------------------------------------+

| METRIC                       | TRADITIONAL CLINIC     | CLINIC POWERED BY AGENT    |
+-----------------------------------------------------------------------------------+

| Admin Time per Month         | 750 Hours              | 83 Hours (↓ 89% Reduction)|
| Annual Nursing Waste Cost    | $540,000               | $59,760                   |
| Annual Graft Losses          | 22 Patients            | 13 Patients (↓ 40% Saved) |
| Total Care Delivery Cost     | $2.6 Million           | $1.5 Million              |
+-----------------------------------------------------------------------------------+

| NET CLINICAL & SYSTEM SAVINGS:  $1.58 MILLION PER YEAR / PER 500-PATIENT COHORT   |
+-----------------------------------------------------------------------------------+


F. PRIOR WORK:
Please describe any prior work, code, designs, or other work your team is building upon so that judges know what was created during the hackathon and what was created prior to the hackathon (if any). e.g. Our project starts with a RAG pipeline I built for my research lab.

I'll write the blurb about scientific research referring to scientific papers read:
https://www.frontiersin.org/journals/pharmacology/articles/10.3389/fphar.2024.1456565/full
https://pmc.ncbi.nlm.nih.gov/articles/PMC11062183/

G. SOCIAL MEDIA POSTS:
Post about your project on social media, then paste at least one post URL below so your entry can be marked complete. 
Sponsor Handles & Hashtags
Share your project on social media! Paste the URL of your public post into the submission form.
Tag the following accounts:
    @AITinkerers
    @OpenAI
    @CopilotKit
    @openrouter
    @exaailabs
    @auth0
    @ambiguousio
    @triggerdotdev
    @mozillaAI
    @googlecloud
Include the hashtag #AgentsEverywhere.
For LinkedIn, use the company names: AI Tinkerers, OpenAI, CopilotKit, OpenRouter, Exa, Auth0, Ambiguous AI, Trigger.dev, Mozilla.ai, Google Cloud.
Paste links to your post(s) below: 
Example posts. Generate, copy, post to socials and paste the links above.
Twitter: Content will appear here
LinkedIn: Content will appear here

Social Media Post URL 1 [LinkedIn Post - Image to match the Repo Image for instant recognition from the Post to the Repo, see above] - should be about the patient benefit
Social Media Post URL 2 [LinkedIn Post - Image Doctor scrolling through the App with stats showing] - focus on benefits to doctors, an agent to help save lives
Social Media Post URL 3 [LinkedIn Post - Image focusing on the Tech Stack - use the logos rendered for the companies?] - Focus on the Agentic architecture
