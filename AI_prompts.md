# AI Prompts Log

## Setup

We are going to build an agentic team for Campus Customs (a collegiate apparel company). 3 pieces of it are 1. MCP server 2. FastAPI backend with multi-agent team 3. React dashboard for human oversight. 

The agent team will be able to communicate with one another. The team will consist of 1. Boss 2. Inventory 3. Accounting 4. Facilities 5. Customer Service

All work will be completed inside hw5 folder. There is a file campus_customes.db that is original shop database. The database will get updated as tickets get resolved. Make a copy of the database called campus_customs_new.db. This will be our working copy. 

Some ground rules: 

1. desk.date_today is "today" for the shop. Use this date for determining what is overdue
2. Vendor leads times are in the vendor table 
3. Vendors will not ship if they have an open unpaid invoice
4. Payments require human approval. Made payments should update the relevant table 
5. Transactions must be refused if there is not enough cash at hand
6. Do not email customers or call real vendors. 


Create an env.local file where I will store my Portkey API key. This is what the agents will be use. All agents will use gpt-6-luna. 

## Problem 1: Vibe coder prompts

Create AI_prompts.md. This will contain a log of every chat I send you. When you find "Problem x: title", this should be a header in the md file and everything that comes after that until the next problem title goes under that heading.

Agents can talk to each other and delegate tasks to each other. 

discount policy tbd. 

Yes, your recorded payment flow sounds good. 

## Problem 2: Study the Campus Customs database

create output/harness.md and for each table, list the fields and one short line describing why that table matters for our agents.

## Problem 3: Build the MCP server

Write an MCP server in mcp_server/ using FastMCP. It will talk to the new db. No need to connect or run it yet. 

Every agent will use the tools in this MCP. Create 3 tools you think will be highest priority for the agents. Keep the names clear. In harness.md, list the MCP tools. For every tool, state what table it reads, what ticket it helps unlock, and one sentence why that tool is the right one for that ticket. Vague lines like "read inventory" will score low so be specific. 

Add a README.md to the mcp_server/ folder that explains what the MCP server is for, what it interacts with, and the tools it has.

## Problem 4: Add the MCP server to vibe coder and test each tool

Add the MCP server to this project so you (claude) can call the tools. Save the connection JSON text in .mcp.json. 

We are going to test each tool. Save evidence in output/mcp_smoke.json. Include my prompt used to test each tool, the tool name, and the tool output. 

Tool 1 test: check the stock of shirts. 

Tool 2 test: What vendor will ship today? 

Tool 3 test: Try to make a payment for which we have insufficient cash

You should do the payment test this one time. The agents (not you) will not be able to do payments

session was re-loaded.

Run what needs to be ran yourself.

## Problem 5: Build the agent team and grow the MCP tools

Lets build those agents! PydanticAI for each agent. Include prompts, models, and agent loops so the can delegate work to each with full connectivity. 

Put the agent prompts in backend/prompts/. One file per agent. Put data types in backend/models.py and agent files in backend/ 

Use the portkey api key and only one gpt-6-lune for each agent. 

Write the prompt, including the shop rules, for each agent based off my ideation here. Be descriptive, anticipate edge cases, and be thorough. The below is not exhaustive.

Boss: number 1 priority is orchestration. make sure work doesn't get duplicated. Should be looped into every communication even if boss won't get involved. Boss will receive updates from other agents and will need to make decisions off of them, if needed. 
Inventory: agent is responsible for checking existing inventory, alerting the right agents when inventory gets low, provide feedback to boss on items that are not selling or are selling faster than stock can keep up 
Accounting: Correct accounting principles are paramount. Accountant should be interested in business success and alert boss of any impending issues. 
Facilities: Campus customs is a quality institution and the facilities bot should ensure that the facilities matches that. 
Customer Service: The customer service agent is patient, clear, and helpful. It should be widely knowledgeable of the offerings from campus customs. 

Add any tools these agents might need to the MCP server so they can work on open tickets. Be exhaustive. Do not have a second shop tools layer that bypasses MCP. 

Have the agents append to output/audit_trail.json as they run. Each loop step, record enough info for post-hoc auditing. Ensure info is appended. 

In harness.md, list each agent and each MCP tool available, along with what table the tool uses. Add a safety section that takes inspiration from Anthropic's constitution. 

Review all prompts and agent interaction for token efficiency upgrades. Vet ideas then implement them. Then add what you did to the harness.md token efficiency section. 

Lastly, update the mcp_server/README so that the tool list matches what is current.

## Problem 6: Plan the 3 tickets

Lets write down what we expect the team to do on each open ticket. Create output/desk-tickets.html which will be double click-able with one tab per ticket (101, 102, 103). Also add "Cash" and "Reflection" tabs which we will flush out later. On each ticket tab fill an expected section only (leave room for an actual section later). For each expected section in a ticket, write who the boss should call first and why, all the agent delegations we expect, and which mcp tools we expect that run to use. Plans that send every agent everywhere is bad planning. Lets get a good plan written down in that expected section. I will ideate with you first, you will flush it out completely:
101: inventory agent will need to check stock, customer service agent will need to let tauhid know his shirt is out. It will need to use inventory tool and a chat tool (that likely wont exist until we get the front end)
102: Accounting agent will be called 
103: Accounting and inventory agent will be called. Inventory tools,

## Problem 7: Backend Routes

We will build the react frontend after this. Now, the backend. In backend/main.py, use FastAPI to add routes that 1. return the three tickets and where they are open or resolved 2. take a ticket id and run your agent team against it 3. return recent agent activity 4. approve a payment or purchase after a human clicks approve 5. return the current checking balance from cash_accounts 6. reset the database to og value when we want a fresh run 

Then, from the backend folder, run uvicorn main:app --reload --port 8000 

In output/harness.md list each route in one line (what URL and what it does)

## Problem 8: Agent dashboard

Now we finally build the dashboard in frontend/ with React and Vite and TypeScript. It should call the routes built in P7. The dashboard should list all 3 tickets, let the user pick one ticket and start the agent team on it, show each agent and what they are saying + doing, mark a ticket resolved when run finishes, show a short summary of what each agent did on a ticket, let the user approve a pay or purchase, show the checking balance (it should drop after an approved pay). Use solid design principles to make the dashboard. Use classic Yale aesthetics throughout. Make it a bit overly so. But should be very useable. 

The front end should talk to the backend at http://localhost:8000 On the backend allow the Vite page origin so the browser is allowed to call those routes. 

Start the board with nmp run dev

Write output/design.md with what was chosen for the dashboard aesthetics and layout and why (including what makes it special)

## Problem 9: Resolve the tickets

Reset the working database data/campus_customs_new.db again so you start clean. Open the frontend, run all tickets via web tools acting as me the user, and then write to the actual section from the runs . Include what tools were used, what they delegated, and which agents worked. Keep the expected section for comparisons. 

On the cash tab of the same output/desk_tickets.html, itemize the money: starting checking balance (after the reset), for each ticket: how cash changed when that ticket resolved, and why, ending checking balance (it must match cash_accounts in working database). Wrong cash will be heavily penalized so ensure proper calculations. 

Save output/resolved_tickets.json for each ticket: id, final status, short outcome, what each agent contributed, and any human approvals output/resolved_board.html: a page you can double click with a screenshot of your react board for each resolved ticket (101, 102, 103)

Append real runs to output/audit_trail.json 

Finish output/harness.md so it covers tables MCP tools, the five agents, API routes, dashboard, and safety rules

## Problem 10: Reflection 

Open output/desk_tickets.html and fill the Reflection tab with my thoughts, but refined and polished by you. 

Ticket 101: nailed inventory first, then accounting, then customer service. The performance was good. It would have been simpler as one agent with tools from a architecture perspective but from an audit and solutioning perspective it was easier with multiple. 

Ticket 102: Correctly identified that only the accounting agent would be used. Performance as good. 

Ticket 103: Correctly identified inventory first but missed the subsequent accounting and customer service delegations. Performance in actuality was not affected

3 new problems Campus Customs might face that this agent team could solve is 1. bulk order negotiations for discounts 2. an order that failed to be placed 3. if the business is not selling merch to match their supply ordered

3 new problems Campus Customs can't address is 1. shipping errors 2. distribution optimization 3. new product discovery

When polishing these answers, refer to the cash and tickets tabs as evidence. Be detailed and include any creative flourishes you believe will help. keep the ideations at the end to 3 total for each but add details as you see fit.

## Problem 11: Submit to GitHub

[Screenshot of the required hw5/ file structure: AI_prompts.md, requirements.txt, .env.example, .gitignore, .mcp.json, README.md, data/ (campus_customs.db, campus_customs_new.db), mcp_server/ (server.py, README.md), frontend/, backend/ (main.py, models.py, prompts/ boss.md, inventory.md, accounting.md, facilities.md, customer_service.md), output/ (harness.md, mcp_smoke.json, desk_tickets.html, design.md, resolved_tickets.json, resolved_board.html, audit_trail.json, github_url.txt)]

Ensure everything fits this file structure. Push this all to https://github.com/shanehaynes/Homework5.git Do not push .env Do include both databases files under data/

README should explain copy original DB to the working copy when you need a clean run, start the MCP server, start the MCP server, start FastAPI backend, start the React board, reset the DB before a full three ticket run
