# Common Issues Documentation

This folder feeds the (upcoming) Common Issues panel on the dashboard.
Write your troubleshooting documentation in `issues.json` — the panel will
render it directly, so adding or editing issues never requires code changes.

## Format

`issues.json` maps each station ID to a list of issues:

```json
{
  "SIF-401": [
    {
      "title": "Short name of the problem",
      "symptoms": "What the operator sees (alerts, behavior, sounds...)",
      "steps": [
        "First thing to try",
        "Second thing to try"
      ],
      "image": "issues/img/my-photo.jpg"
    }
  ]
}
```

- `title` and `steps` are required; `symptoms` and `image` are optional.
- Put photos/diagrams in the `img/` subfolder (create it when you add the
  first image). Any web image format works: .jpg, .png, .gif, .svg, .webp.
- The `image` path is relative to the frontend's public folder, so
  `issues/img/my-photo.jpg` refers to
  `frontend/public/issues/img/my-photo.jpg`.
- One image per issue to start with; if you want multiple images or captions
  per issue, note it and the panel can be extended.
