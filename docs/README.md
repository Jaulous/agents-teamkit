# Agents TeamKit Documentation

This directory is organized by the questions a new contributor or adapter author is likely to ask.

## Start Here

- [Product scope](product-scope-v0.1.md): what v0.1 includes and deliberately leaves out.
- [Changelog](../CHANGELOG.md): public release history and compatibility notes.
- [Architecture](architecture.md): layered model, adapter boundary, and run workspace responsibilities.
- [User model](user-model.md): business-facing concepts and how they map into TeamKit Core.

## Define A Team

- [Team YAML spec](team-yaml-spec.md): the `team.yaml` protocol.
- [Context Items](context-items.md): managed files, runtime snapshots, and visibility.
- [Expert runtime rules](expert-runtime-rules.md): how generated experts should coordinate during a run.

## Run And Coordinate

- [Command reference](teamkit-commands.md): stable command layer.
- [Run workspace](run-workspace.md): files created for each task run.
- [Coordination model](coordination-model.md): Graph, Topic, Context Item, and Message semantics.
- [Communication protocol](communication-protocol.md): expert-to-expert request and reply rules.
- [Collaboration workspace](collaboration-workspace.md): ownership rules that prevent experts from overwriting each other.

## Adapter Work

- [WorkBuddy adapter](workbuddy-adapter.md): current package-level WorkBuddy export and install flow.
- [Directory model](directory-model.md): tool home, team roots, and run data placement.
- [WorkBuddy bridge](workbuddy-bridge.md): delivery guidance and package-level bridge boundaries.
- [MVP capability map](mvp-capability-map.md): implemented, deferred, and explicitly excluded capabilities.

## Public Project Notes

The repository should present TeamKit Core as platform-independent. WorkBuddy-specific details belong in adapter documents and optional install sections, not in the core model.
