# Pitch script (2 minutes)

Thirty Power Platform apps, and nobody can tell you every rule inside them. That's the real migration risk: not rewriting code, but losing a rule nobody wrote down.

We built a factory that treats the old app as the specification. It parses every formula, flow, table and role with Microsoft's own parser. A local language model explains each rule in plain English, but it doesn't write the code and it can't approve anything. A deterministic compiler generates the .NET 8 API, React UI, Cosmos DB design and Azure Bicep.

Then we prove it. We run the original Power Fx in Microsoft's interpreter, then our generated C# on the same frozen inputs, and compare. On our insurance claims app, 25 of 45 rules are proven over 1,209 cases, with zero failures. On Microsoft's real Approvals Kit we found 117 of 124 hand-labelled rules, and every one of the 1,464 compiled formulas matches.

We'll also tell you what we can't prove. Most Approvals Kit logic lives in cloud flows, and today we design those but don't generate them. So the dashboard shows zero proven rules there, not a green tick. Everything unproven, or touching age, postcode or vulnerability, goes to a human-review queue that the model can't edit.

The factory improves itself under a protocol you can audit: one change at a time, a held-out app it never tunes on, and reverted experiments kept on the record.

For thirty apps, the effort model says flows are the bottleneck, so that's where the next month goes. Give us three of your apps in week one and we'll replace our assumptions with your measurements.
