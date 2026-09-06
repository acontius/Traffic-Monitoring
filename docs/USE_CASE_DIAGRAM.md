# Use Case Diagram

Actors and use cases strictly reflect what is implemented — nothing here is
invented. Two roles named in the SRS-style code comments (Administrator,
Operator) are **not actually distinguished** in the codebase: the `users`
table has a `role` column but every domain router depends only on
`get_current_user` with no role check, so there is one authenticated-user
permission level in practice. That's shown below as a single
"Authenticated User" actor with a note, rather than inventing two enforced
roles.

```mermaid
graph LR
    User["Authenticated User<br/>(role column exists,<br/>not yet enforced)"]
    Device["Traffic Counting Device<br/>(camera / simulator)"]
    RoadAuth["External Road Authority<br/>(mocked: Backend/mock_external)"]
    SMS["SMS Gateway<br/>(mocked: Backend/mock_external)"]

    User --> UC1[Login / refresh / logout]
    User --> UC2[View dashboard / live device status]
    User --> UC3[View device detail & history]
    User --> UC4[Acknowledge alert]
    User --> UC5[View / export report - CSV or JSON]
    User --> UC6[Manually override a reading]
    User --> UC7[Manage traffic events - calendar context]
    User --> UC8[Resend a failed forwarding attempt]
    User --> UC9[Register / update a device]
    User --> UC10["Train / retrain ML model<br/>(CLI or POST /ml/train)"]
    User --> UC11[Review anomaly event status]
    User --> UC12[Tune reconstruction formula weights]

    Device --> UC13[Send a traffic-count reading]

    UC13 -.->|triggers| UC14[System: validate + score + persist]
    UC14 -.->|on gap| UC15[System: reconstruct missing interval]
    UC14 -.->|on anomaly/gap/failure| UC16[System: raise alert]
    UC14 -.->|on accepted/reconstructed data| UC17[System: forward to Road Authority]
    UC16 -.->|critical only| UC18[System: send SMS]

    UC17 --> RoadAuth
    UC18 --> SMS
```
