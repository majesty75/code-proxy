english: I have a system called UTA server. UTA stands for Unified Test Framework which is legacy system for remote test execution on boards.
The system runs automated test which can be controlled from web UI. the web URL for each server is different.
the physical configuration is like this:

1. There are multiple servers.
2. Each server is connected to Racks.
3. Each rack have mutliple rows and rows have slots.
4. each slot have one board on which test runs.

All boards generate test logs which is stored in UTA in "uta" folder and is shared over the network sharing.
the logs are stored in \\server_ip\uta\UTA_FULL_Logs and keep getting updated when the test exeuction is currently in progress.
Once the test is passed/failed the log is moved to \\server_ip\uta\UTA_LOGS_BACKUP\UTA_LOGS_BCAKUP_07_04_2026 kind of folder.

The log is not in any form and i arbitrary text which contains various kind of variables and debug messages and everything.

I want to create a system that help me visualize the current test which are running. also I want to have big data capabilities and comparison of current live test results,
with previous FW versions / other products.

The logs size vary from MB to double digit GBs hence it is not possible to send entire log over the internet and process it.

I want a distributed system as shown in the diagram which runs file watcher in UTA server and sends chunks in realtime which is parsed in main server and stored in database which will
best suitable for unstructured data and have very good performance with big data. I then want to utilize this data for visualiZations, data analytics and AI.
