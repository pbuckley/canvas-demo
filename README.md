# Demo of Canvas View
some placeholder text here

## Improvement Ideas

* ~~adapt to pull in other pipelines matching the convention~~
* generate deploy summary
** Should have a higher priority than the deploy jobs themselves so it
runs first, my hosted agents are LIMITED
* cache results from previous get_releases so the rollback is near instantaneous

### blue/green and canary deploys?

what can I show to illustrate this pattern?

### dynamic tag convention

Right now, I'm using deployable-svc. Can I switch to another? Can I
make one up on the spot?

### automatic service pipeline adding

why would I manually add a pipeline tagged `deployable-svc`? tf this up

### support windows, linux, mac server targets

seeing more than the windows emoji would be good

this includes changing deploy_pattern and script_pattern to handle
other emojis for the deploys

### local_run so I can generate the SUMMARY.MD locally

done? still not tested extensively (or not enough)

### trigger the pipeline (input step) remotely with meta-data

~~build it from the CLI locally so I can stop inputting everything every
time ohmahgosh~~

## existing bugs

unknown-region is broken - we aren't getting any regions!?!?!

we lost looping, we run once and bail, the final/finish logic is borked

