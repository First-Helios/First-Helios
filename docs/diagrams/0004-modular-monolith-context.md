# ADR-0004 modular-monolith context

This diagram shows runtime composition and ownership. Solid arrows point from
an in-process caller to the contract or store it uses. Dashed arrows show
data lineage from Bronze through Silver to Gold; neither arrow style denotes
foreign-key direction. All modules ship from one repository and share one
Postgres transaction boundary.

```mermaid
flowchart LR
    sources["Public and first-party sources"]
    consumers["API consumers"]
    reviewer["Human identity reviewer"]
    replay["Replay payload storage"]

    subgraph helios["Helios modular monolith - one release unit"]
        direction LR

        subgraph entrypoints["Entrypoints"]
            collector["Collector / cron / backfill"]
            api["Read API"]
            reviewcmd["Review command - deferred UI"]
        end

        parser["helios_parsing<br/>pure extraction"]

        subgraph modules["In-process modules"]
            provenance["Shared provenance<br/>Bronze owner"]
            identity["Shared identity<br/>Silver owner"]
            menu["Menu vertical<br/>Silver owner"]
            gold["Gold projections<br/>read-model owner"]
        end

        collector --> provenance
        collector --> parser
        collector --> identity
        collector --> menu
        reviewcmd --> identity
        identity --> provenance
        menu --> provenance
        menu --> identity
        gold --> provenance
        gold --> identity
        gold --> menu
        api --> identity
        api --> gold
    end

    subgraph postgres["One PostgreSQL database"]
        bronze[("bronze<br/>source claims and evidence")]
        identitydb[("identity<br/>subjects and decision history")]
        menudb[("menu<br/>typed vertical facts")]
        golddb[("gold<br/>rebuildable read models")]
        publicdb[("public<br/>alembic_version only")]
    end

    sources --> collector
    collector --> replay
    replay --> collector
    reviewer --> reviewcmd
    api --> consumers

    provenance --> bronze
    identity --> identitydb
    menu --> menudb
    gold --> golddb
    entrypoints -. migration coordination .-> publicdb

    bronze -. interpreted identity .-> identitydb
    bronze -. validated vertical facts .-> menudb
    identitydb -. scopes vertical facts .-> menudb
    bronze -. derived .-> golddb
    identitydb -. derived .-> golddb
    menudb -. derived .-> golddb
```

The review command is an in-process entrypoint, not a service boundary. Its
UI and operational workflow are deferred; the append-only decision contract
is not.
