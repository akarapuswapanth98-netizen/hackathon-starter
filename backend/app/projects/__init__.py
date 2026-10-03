"""Problem-specific project modules.

Each subpackage is self-contained: it may import the reusable toolkit
(app.core, app.ai, app.agents, app.ml, app.maps, app.database) but the
toolkit never imports a project. That one-way rule keeps FoodLink Predict
(and any future project) additive.
"""