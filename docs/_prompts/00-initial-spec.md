# Home IOT inventory, calendaring, mapping tool

Build a plan for creating a web application focused on technically-adept homeowners who need to manage all of the mechanical, electrical, HVAC, and various IOT devices around their property.  Help technical homeowners understand, document, maintain, and troubleshoot their homes by combining a homeowner-controlled equipment database with Home Assistant context and optional extensions.

## Persona

- You are an experienced full-stack open source software developer.
- Use only permissively-licensed open source code from well-rated and maintained projects or from the ASF; never use GPL or any FSF licensed code.
- Write clean, modular, secure, and correct code following best practices for linting in modern environments.
- Plan on making the project open source under Apache-2.0 when done.

## Key Product Features

- A simple but elegant user interface for the first version.
- Basic inventory of items, like household appliances, HVAC units, lighting, and IOT devices, both by name, model number, date installed, and various links to user manuals or instructions.
- Simple calendaring system, to remind the user to change the fridge water filter every 6 months, or to check the sump pump backup battery yearly.
- Simple update system, so when a user changes the fridge water filter, it can be marked and any reminder reset to the correct interval.
- Home Assistant https://developers.home-assistant.io/ integration, so that any IOT devices can easily be queried or controlled for home automation projects.
- Basic home layout or map features, so that all items can easily be assigned to specific locations; either within a room, or in a room on a specific part of one wall, or attached to a window.
- Simple graphical viewer showing each device in place in the house; this can use fairly simple mapping or imagery for the first release.
- Graphical viewer that allows uploading photos of devices or of walls within the house; this does not need to be completely photo-accurate; just good enough to understand which IOT lightswitch is which for example.
- Future additions: for advanced homeowners, add database entries for things like electrical conduits, breaker boxes, or plumbing lines and shutoff valves. Example: a calendar reminder in November reminds the user to turn off the water to the outdoor hose at the shutoff valve, and drain the hose.

## Functional Requirements

- Clean, maintainable software stack with a robust backup and restore system.
- User permission levels for accessing data, starting with Admin, Resident, and Guest.
- Prefer using existing open source software libraries for core features instead of writing new code.
- Can run locally on a base level laptop without a public internet connection, or on any common cloud host.
- Easy integration into a Home Assistant install; favor using Home Assistant naming, API, or coding conventions for any IOT integrations; plan to build a Home Assistant plugin in future versions to handle actual automations; ensure our application works even without Home Assistant.
- Use our own UUID for all items; this allows reliably tracking things that might not appear in Home Assistant; include other obvious ID-like data like MAC address, serial number, etc. also.
- Provide basic read-only REST endpoints for all core features for integration into other applications.

## Potential User Workflows - sample

| Workflow | What success looks like |
| :-- | :-- |
| Add a new unconnected appliance | Photograph its label, enter model and serial number, find the link to user manual, assign a room and location within the room, and create a maintenance schedule. |
| Import Home Assistant devices | Preview discovered devices, match existing assets, and import selected records without duplicates. |
| Troubleshoot a device | See its documentation, current Home Assistant context, network connection, power source, and service history in one place. |
| Perform maintenance | Find the correct part, follow a documented procedure, record completion and cost, and calculate the next due date. |
| Find equipment physically | Search by room, system, circuit, tag, or—through a plugin—position on a floor plan. |
| Recover or transfer the records | Restore a backup or export selected records without needing Home Assistant to be running. |

