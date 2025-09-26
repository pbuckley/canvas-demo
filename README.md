# Demo of Canvas View
some placeholder text here

## Improvement Ideas

* ~~adapt to pull in other pipelines matching the convention~~
* ~~generate deploy summary~~
** ~~Should have a higher priority than the deploy jobs themselves so it
runs first, my hosted agents are LIMITED~~
*** can I lower the general priority of the deploys a bit? the higher
priority of 10 for my generate summary is no workee
* cache results from previous get_releases so the rollback is near instantaneous
* annotation is cool and all, but I want final form to be a json artifact, too, for consumption by future automated processes

### blue/green and canary deploys?

what can I show to illustrate this pattern?

### dynamic tag convention

Right now, I'm using deployable-svc. Can I switch to another? Can I
make one up on the spot?

### automatic service pipeline adding

why would I manually add a pipeline tagged `deployable-svc`? tf this up
and/or make this use a template so we enforce our convention of metadata

### support windows, linux, mac server targets

seeing more than the windows emoji would be good

this includes changing deploy_pattern and script_pattern to handle
other emojis for the deploys

### local_run so I can generate the SUMMARY.MD locally

~~done? still not tested extensively (or not enough)~~

### trigger the pipeline (input step) remotely with meta-data

~~build it from the CLI locally so I can stop inputting everything every
time ohmahgosh~~

## existing bugs

~~unknown-region is broken - we aren't getting any regions!?!?!~~
we get a region now, but it is a best guess heuristic based on region
order, not the precision that I wanted :( - I'm thinking I may need to
put the region in the label of the deploys, but that will look uggo

~~we lost looping, we run once and bail, the final/finish logic is borked~~
