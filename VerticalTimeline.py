#Author-Thomas Axelsson
#Description-Provides a vertical timeline.

# This file is part of VerticalTimeline, a Fusion 360 add-in that
# provides a vertical timeline.
#
# Copyright (C) 2020  Thomas Axelsson
#
# This work is dual-licensed under GPL 3.0 (or any later version) and MIT.
# You can choose between one of them if you use this work.

# Put add-in folder in %appdata%\Autodesk\Autodesk Fusion 360\API\AddIns

# Need to use Visual Studio Code Python extension version 2019.9.34911
# to be able to debug with Fusion.. (2020-07-23)

import adsk.core, adsk.fusion, adsk.cam, traceback

from collections import defaultdict
import json
import os
import sys
import threading

NAME = 'Vertical Timeline'
FILE_DIR = os.path.dirname(os.path.realpath(__file__))

# Import relative path to avoid namespace pollution
from .thomasa88lib import utils
from .thomasa88lib import events
from .thomasa88lib import timeline
from .thomasa88lib import settings
from .thomasa88lib import manifest
from .thomasa88lib import error

# Force modules to be fresh during development
import importlib
importlib.reload(thomasa88lib)
importlib.reload(thomasa88lib.events)
importlib.reload(thomasa88lib.timeline)
importlib.reload(thomasa88lib.settings)
importlib.reload(thomasa88lib.manifest)
importlib.reload(thomasa88lib.error)

ui = None
app = None
error_catcher = thomasa88lib.error.ErrorCatcher(msgbox_in_debug=False)
events_manager = thomasa88lib.events.EventsManager(error_catcher)
manifest = thomasa88lib.manifest.read()

html_ready = False

timeline_item_count = 0
timeline_marker_position = -1

settings = thomasa88lib.settings.SettingsManager(
    { 'enabled': False }
)

def get_enabled():
    return settings['enabled']

def set_enabled(value):
    settings['enabled'] = value

# Occurrence types
OCCURRENCE_UNKNOWN_COMP = 0
OCCURRENCE_NEW_COMP = 1
OCCURRENCE_COPY_COMP = 2
OCCURRENCE_SHEET_METAL = 3
OCCURRENCE_BODIES_COMP = 4

TIMELINE_STATUS_OK = 0
TIMELINE_STATUS_PRODUCT_NOT_READY = 1
TIMELINE_STATUS_NOT_PARAMETRIC = 2

OCCURRENCE_RESOURCE_MAP = {
    OCCURRENCE_NEW_COMP: ('Fusion/UI/FusionUI/Resources/Modeling/BooleanNewComponent', ''),
    OCCURRENCE_COPY_COMP: ('Fusion/UI/FusionUI/Resources/Assembly/CopyPasteInstance', ''),
    OCCURRENCE_SHEET_METAL: ('Neutron/UI/Base/Resources/Browser/ComponentSheetMetal', ''),
    #'FusionCreateComponentFromBodyEditCommand' seems to actually create a new component
    OCCURRENCE_BODIES_COMP: ('Fusion/UI/FusionUI/Resources/Assembly/CreateComponentFromBody', ''),
    OCCURRENCE_UNKNOWN_COMP: ('Fusion/UI/FusionUI/Resources/finish/finishX', '')
}

PLANE_RESOURCE_MAP = {
    'ConstructionPlaneOffsetDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_offset', 'FusionDcEditWorkPlaneByPlaneOffsetCommand'),
    'ConstructionPlaneAtAngleDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_angle', 'FusionDcEditWorkPlaneByLineAndAngleCommand'),
    'ConstructionPlaneTangentDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_tangent', 'FusionDcEditWorkPlaneTangentToCylinderCommand'),
    'ConstructionPlaneMidplaneDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_midplane', 'FusionDcEditWorkPlaneFromTwoPlanesCommand'),
    'ConstructionPlaneTwoEdgesDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_two_axis', 'FusionDcEditWorkPlaneFromTwoLinesCommand'),
    'ConstructionPlaneThreePointsDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_three_points', 'FusionDcEditWorkPlaneFromThreePointsCommand'),
    'ConstructionPlaneTangentAtPointDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_point_face', 'FusionDcEditWorkPlaneTangentToFaceAtPointCommand'),
    'ConstructionPlaneDistanceOnPathDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_onpath', 'FusionDcEditWorkPlaneAlongPathCommand'),
}

FEATURE_RESOURCE_MAP = {
    # This list is hand-crafted. Please respect the work put into this list and
    # retain the Copyright and License stanzas if you copy it.
    # Helpful tools: trace_feature_image function, ImageSorter, Process Monitor.
    # Resources are found in %localappdata%\Autodesk\webdeploy\production\*\
    'Sketch': ('Fusion/UI/FusionUI/Resources/sketch/Sketch_feature', 'SketchActivate'),
    'FormFeature': ('Fusion/UI/FusionUI/Resources/TSpline/TSplineBaseFeatureCreation', 'TSplineBaseFeatureActivate'),
    'LoftFeature': lambda i: ('Fusion/UI/FusionUI/Resources/solid/loft', 'FusionLoftEditCommand') if i.entity.isSolid else ('Fusion/UI/FusionUI/Resources/surface/loft', 'FusionSurfaceLoftEditCommand'),
    'ExtrudeFeature': lambda i: ('Fusion/UI/FusionUI/Resources/solid/extrude', 'FusionExtrudeEditCommand') if i.entity.isSolid else ('Fusion/UI/FusionUI/Resources/surface/extrude', 'FusionSurfaceExtrudeEditCommand'),
    'Occurrence': lambda i: OCCURRENCE_RESOURCE_MAP[thomasa88lib.timeline.get_occurrence_type(i)],
    'BoundaryFillFeature': ('Fusion/UI/FusionUI/Resources/surface/surface_sculpt', 'FusionSculptEditCommand'),
    'SurfaceDeleteFaceFeature': ('Fusion/UI/FusionUI/Resources/modify/surface_delete', 'FusionDcSurfaceDeleteFaceEditCommand'),
    'RevolveFeature': lambda i: ('Fusion/UI/FusionUI/Resources/solid/revolve', 'FusionRevolveEditCommand') if i.entity.isSolid else ('Fusion/UI/FusionUI/Resources/surface/revolve', 'FusionSurfaceRevolveEditCommand'),
    'SweepFeature': lambda i: ('Fusion/UI/FusionUI/Resources/solid/sweep', 'FusionSweepEditCommand') if i.entity.isSolid else ('Fusion/UI/FusionUI/Resources/surface/sweep', 'FusionSurfaceSweepEditCommand'),
    'RibFeature': ('Fusion/UI/FusionUI/Resources/solid/rib', 'FusionDcRibEditCommand'),
    'WebFeature': ('Fusion/UI/FusionUI/Resources/solid/web', 'FusionDcWebEditCommand'),
    'Thomasa88Feature': ('Vertical/Timeline', 'FeatureMap'),
    'BoxFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_box', 'BoxPrimitiveEditCommand'),
    'CylinderFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_cylinder', 'CylinderPrimitiveEditCommand'),
    'SphereFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_sphere', 'SpherePrimitiveEditCommand'),
    'TorusFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_torus', 'TorusPrimitiveEditCommand'),
    'CoilFeature': ('Fusion/UI/FusionUI/Resources/solid/Coil', 'CoilPrimitiveEditCommand'),
    'PipeFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_pipe', 'PipePrimitiveEditCommand'),
    'RectangularPatternFeature': ('Fusion/UI/FusionUI/Resources/pattern/pattern_rectangular', 'FusionDcRectangularPatternEditCommand'),
    'CircularPatternFeature': ('Fusion/UI/FusionUI/Resources/pattern/pattern_circular', 'FusionDcCircularPatternEditCommand'),
    'PathPatternFeature': ('Fusion/UI/FusionUI/Resources/pattern/pattern_path', 'FusionDcPathPatternEditCommand'),
    'MirrorFeature': ('Fusion/UI/FusionUI/Resources/pattern/pattern_mirror', 'FusionDcMirrorPatternEditCommand'),
    'ThickenFeature': ('Fusion/UI/FusionUI/Resources/surface/thicken', 'FusionDcSurfaceThickenEditCommand'),
    'BaseFeature': ('Fusion/UI/FusionUI/Resources/Modeling/BaseFeature', 'BaseFeatureActivate'),
    'RemoveFeature': ('Fusion/UI/FusionUI/Resources/_return', ''),
    'HoleFeature': ('Fusion/UI/FusionUI/Resources/solid/hole', 'FusionDcHoleEditCommand'),
    'ThreadFeature': ('Fusion/UI/FusionUI/Resources/solid/thread', 'FusionDcThreadEditCommand'),

    # Solid Modify
    'FilletFeature': ('Fusion/UI/FusionUI/Resources/Modeling/FilletEdges', 'FusionDcFilletEditCommand'),
    'ChamferFeature': ('Fusion/UI/FusionUI/Resources/Modeling/Chamfer', 'FusionDcChamferEditCommand'),
    'ShellFeature': ('Fusion/UI/FusionUI/Resources/Modeling/ShellBody', 'FusionDcShellFeatureEditCommand'),
    'DraftFeature': ('Fusion/UI/FusionUI/Resources/solid/draft', 'FusionDcDraftEditCommand'),
    'ScaleFeature': ('Fusion/UI/FusionUI/Resources/modify/scale', 'FusionDcScaleEditCommand'),
    'CombineFeature': ('Fusion/UI/FusionUI/Resources/modify/combine', 'FusionCombineEditCommand'),
    'ReplaceFaceFeature': ('Fusion/UI/FusionUI/Resources/modify/replace_face', 'FusionDcReplaceFaceEditCommand'),
    'SplitFaceFeature': ('Fusion/UI/FusionUI/Resources/modify/split_face', 'FusionDcSplitFaceEditCommand'),
    'SplitBodyFeature': ('Fusion/UI/FusionUI/Resources/modify/split', 'FusionDcSplitBodyEditCommand'),

    # Surface Create only
    'OffsetFacesFeature': ('Fusion/UI/FusionUI/Resources/Modeling/OffsetFaces', 'FusionOffsetFacesEditCommand'),
    'PatchFeature': ('Fusion/UI/FusionUI/Resources/surface/patch', 'FusionSurfacePatchEditCommand'),
    'RuledSurfaceFeature': ('Fusion/UI/FusionUI/Resources/surface/ruled', 'FusionDcSurfaceRuledEditCommand'),
    'OffsetFeature': ('Fusion/UI/FusionUI/Resources/surface/offset', 'FusionDcSurfaceOffsetEditCommand'),

    # Surface Modify only
    'TrimFeature': ('Fusion/UI/FusionUI/Resources/surface/trim', 'FusionDcSurfaceTrimEditCommand'),
    'ExtendFeature': ('Fusion/UI/FusionUI/Resources/surface/extend', 'FusionDcSurfaceExtendEditCommand'),
    'StitchFeature': ('Fusion/UI/FusionUI/Resources/surface/stitch', 'FusionSurfaceStitchEditCommand'),
    'UnstitchFeature': ('Fusion/UI/FusionUI/Resources/surface/unstitch', 'FusionSurfaceUnStitchEditCommand'),
    'ReverseNormalFeature': ('Fusion/UI/FusionUI/Resources/modify/surface_reverse_normal', 'FusionDcReverseNormalEdit'),

    # Assembly
    'Joint': ('Fusion/UI/FusionUI/Resources/Assembly/joint', 'DcEditJointAssembleCmd'),
    'AsBuiltJoint': ('Fusion/UI/FusionUI/Resources/Assembly/JointAsBuilt', 'DcEditJointAsBuiltCmd'),
    'JointOrigin': ('Fusion/UI/FusionUI/Resources/construction/jointorigin', 'EditJointOriginR2Cmd'),
    'RigidGroup': ('Fusion/UI/FusionUI/Resources/Assembly/RigidGroup', 'DcEditRigidGroupCmd'),
    'Snapshot': ('Fusion/UI/FusionUI/Resources/Assembly/Snapshot', 'SnapshotActivate'),

    # Planes
    'ConstructionPlane': lambda i: PLANE_RESOURCE_MAP.get(thomasa88lib.utils.short_class(i.entity.definition)),
    
    # Not allowed to access entity for these (API mismatch?)
    # Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-cannot-access-entity-of-quot-move-quot-feature/m-p/9651921
    # Move: FusionDcMoveCopyEditCommand
    # Align: FusionDcAlignEditCommand
    # '2 : InternalValidationError : res': 'Fusion/UI/FusionSheetMetalUI/Resources/Flange',
    # '2 : InternalValidationError : res': 'Fusion/UI/FusionSheetMetalUI/Resources/Bend',
    # '2 : InternalValidationError : res': 'Fusion/UI/FusionSheetMetalUI/Resources/ConvertToSheetMetal',
    # '2 : InternalValidationError : res': 'Fusion/UI/FusionSheetMetalUI/Resources/FlatPattern',
    # insert derive feature: 'Fusion/UI/FusionUI/Resources/Derive/CloneWM',
}

def get_feature_image(obj):
    match = get_feature_res(obj)

    if not match or not match[0]:
        # Image not mapped
        image = 'Fusion/UI/FusionUI/Resources/finish/finishX'
    else:
        image = match[0]
    
    return get_image_path(image)

def get_feature_edit_command_id(obj):
    match = get_feature_res(obj)

    if not match or not match[1]:
        return None
    else:
        return match[1]

def get_feature_res(obj):
    entity = obj.entity
    fusionType = thomasa88lib.utils.short_class(entity)
    match = FEATURE_RESOURCE_MAP.get(fusionType)
    if callable(match):
        match = match(obj)
    return match

def get_image_path(subpath):
    path = f'{thomasa88lib.utils.get_fusion_deploy_folder()}/{subpath}/16x16.png'
    if os.path.exists(path):
        return path
    else:
        print(f'File does not exist: {path}')
        return None

def find_commands(substring):
    return [c.id for c in ui.commandDefinitions if substring in c.id.lower()]

def find_commands_by_resource_folder(folder):
    commands = []
    for c in ui.commandDefinitions:
        try:
            if folder in c.resourceFolder.lower():
                commands.append(c.id)
        except:
            pass
    return commands

# ui.commandDefinitions.itemById('').resourceFolder
# design.rootComponent.allOccurrences[0].component.sketches

def invalidate(send=True, clear=False):
    global timeline_item_count
    global timeline_marker_position
    global html_ready

    palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')

    if not palette or not html_ready:
        return

    message = ""
    features = []
    max_parents = 0
    if not clear:
        timeline_status, timeline = thomasa88lib.timeline.get_timeline()
        if timeline_status == TIMELINE_STATUS_OK:
            timeline_item_count = timeline.count
            timeline_marker_position = timeline.markerPosition
            features, max_parents = get_features(timeline)
        elif timeline_status == TIMELINE_STATUS_PRODUCT_NOT_READY:
            timeline_item_count = -1
            timeline_marker_position = -1
        elif timeline_status == TIMELINE_STATUS_NOT_PARAMETRIC:
            timeline_item_count = -1
            timeline_marker_position = -1
            message = "Design is not parametric"
        else:
            print("Unhandled timeline status:", timeline_status)

    action = 'setTimeline'
    data = {
         'features': features,
         'max-parents': max_parents,
         'message': message,
    }

    if not send:
        # Cannot do sendInfoToHTML inside the HTML event handler. We either have to use htmlArgs.returnData or
        # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
        html_command = {'action': 'setTimeline', 'data': data}
        return html_command
    else:
        palette.sendInfoToHTML('setTimeline', json.dumps(data))

class TimelineObjectNode:
    def __init__(self, obj, id):
        self.obj = obj
        self.id = id
        self.children = []

timeline_cache_tree = None
timeline_cache_map = None
def get_features(timeline):
    global timeline_cache_tree, timeline_cache_map
    flat_timeline = thomasa88lib.timeline.flatten_timeline(timeline)
    timeline_cache_tree, timeline_cache_map = build_timeline_tree(flat_timeline)

    component_parent_map = get_component_parent_map()

    return get_features_from_node(timeline_cache_tree, component_parent_map)

def get_features_from_node(timeline_tree_node, component_parent_map):
    features = []
    max_parents = 0
    for i, child_node in enumerate(timeline_tree_node.children):
        obj = child_node.obj

        feature = {
            'id': str(child_node.id),
            'name': obj.name,
            'suppressed': obj.isSuppressed,
            'rolledBack': obj.isRolledBack,
            }

        # Might there be empty groups?
        if child_node.children:
            # Group
            feature['type'] = 'GROUP'
            feature['image'] = get_image_path('Fusion/UI/FusionUI/Resources/Timeline/GroupFeature')
            feature['children'], group_max_parents = get_features_from_node(child_node,
                                                                            component_parent_map)
            if group_max_parents > max_parents:
                max_parents = group_max_parents
        else:
            # Not group
            try:
                entity = obj.entity
            except RuntimeError as e:
                entity = None
            
            if entity:
                feature['type'] = thomasa88lib.utils.short_class(obj.entity)
                feature['image'] = get_feature_image(obj)
                parents = get_feature_parent_path(component_parent_map,
                                                  obj)
                feature['parent-components'] = parents
                if len(parents) > max_parents:
                    max_parents = len(parents)
            else:
                # Move and Align and more does not allow us to access their entity attribute
                # Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-cannot-access-entity-of-quot-move-quot-feature/m-p/9651921

                if obj.name.startswith('Derived from '):
                    feature['type'] = 'InsertDerive'
                    feature['image'] = get_image_path('Fusion/UI/FusionUI/Resources/Derive/CloneWM')
                else:
                    feature['type'] = '? (Feature info access prohibited by Fusion 360)'
                    feature['image'] = get_image_path('Fusion/UI/FusionUI/Resources/TSpline/Error')

            if feature['type'] == 'Occurrence':
                # Fusion uses a space separator for the timeline object name, but sometimes the first part is empty.
                # Strip the whitespace to make the list cleaner.
                feature['name'] = feature['name'].lstrip()
                if thomasa88lib.timeline.get_occurrence_type(obj) != OCCURRENCE_BODIES_COMP:
                    # Name is a read-only instance variant of the component's name,
                    # with a prefix on it.
                    # Let the user modify the component's name instead
                    feature['edit-name'] = obj.entity.component.name

        features.append(feature)

    return (features, max_parents)

def get_feature_parent_path(component_parent_map, obj):
    design = app.activeProduct

    feature = obj.entity
    feature_type = thomasa88lib.utils.short_class(feature)
    if feature_type == 'Occurrence':
        if obj.isRolledBack or obj.isSuppressed:
            # No parent component will be available
            return []
        parent_name = component_parent_map[feature.component.name]
    elif feature_type == 'ConstructionPlane':
        if (feature.parent.classType() == 'adsk::fusion::Component' and
            feature.parent != design.rootComponent):
            parent_name = feature.parent.name
        else:
            return []
    elif not hasattr(feature, 'parentComponent'):
        if feature_type not in [ 'Snapshot' ]:
            print("Vertical Timeline: Unhandled missing parent for " + feature.classType())
        return []
    elif feature.parentComponent == design.rootComponent:
        return []
    else:
        parent_name = feature.parentComponent.name

    path = []
    while parent_name:
        path.append(parent_name)
        # If the parent component was suppressed or rolled back,
        # we won't find it, so stop in that case (get() will return None).
        parent_name = component_parent_map.get(parent_name)
    
    path.reverse()
    return path
    
    

def build_timeline_tree(flat_timeline):
    # The timeline tree returned from Fusion depends on the view state of
    # the GUI timeline control. Objects are grouped/nested only if a group
    # is collapsed in the GUI. Flatten the timeline to always get the same
    # result.

    next_id = 0
    def next_node_id():
        nonlocal next_id
        node_id = next_id
        next_id += 1
        return node_id

    def new_node(obj):
        node_id = next_node_id()
        node = TimelineObjectNode(obj, node_id)
        id_map[node_id] = node
        return node

    id_map = {}
    top_node = new_node(None)
    in_node = top_node
    group_nodes = [top_node]

    def get_group_node(group_obj):
        for group_node in group_nodes:
            if group_node.obj == group_obj:
                return group_node
        group_node = new_node(group_obj)
        group_nodes.append(group_node)
        parent_node = get_group_node(group_obj.parentGroup)
        parent_node.children.append(group_node)
        return group_node
    
    for obj in flat_timeline:
        node = new_node(obj)
        parent_obj = obj.parentGroup
        if parent_obj != in_node.obj:
            in_node = get_group_node(parent_obj)
        in_node.children.append(node)

    return top_node, id_map

def get_component_parent_map():
    design = app.activeProduct
    component_parent_map = {}
    parent_map_occurrence(component_parent_map,
     None,
     design.rootComponent.occurrences)

    return component_parent_map

def parent_map_occurrence(component_parent_map, parent_name, occurrences):
    for occurrence in occurrences:
        name = occurrence.component.name
        component_parent_map[name] = parent_name
        parent_map_occurrence(component_parent_map,
         name,
         occurrence.childOccurrences)

def get_view_drop_down():
    qat = ui.toolbars.itemById('QAT')
    file_drop_down = qat.controls.itemById('FileSubMenuCommand')
    view_drop_down = file_drop_down.controls.itemById('ViewWidgetCommand')
    return view_drop_down

def check_timeline():
    global timeline_item_count
    global timeline_marker_position
    global html_ready
    timeline_status, timeline = thomasa88lib.timeline.get_timeline()
    if timeline_status == TIMELINE_STATUS_OK:
        if (timeline.count != timeline_item_count or
            timeline.markerPosition != timeline_marker_position):
            invalidate()
    else:
        timeline_item_count = -1
        timeline_marker_position = -1

def run(context):
    global ui, app
    debug = False
    with error_catcher:
        app = adsk.core.Application.get()
        ui = app.userInterface

        # Add a command that displays the palette
        toggle_palette_cmd_def = ui.commandDefinitions.itemById('thomasa88_showVerticalTimeline')

        if not toggle_palette_cmd_def:
            toggle_palette_cmd_def = ui.commandDefinitions.addButtonDefinition(
                'thomasa88_showVerticalTimeline',
                'Toggle Vertical Timeline',
                'Vertical Timeline\n\n' +
                'A vertical timeline, that shows feature names. Timeline functionality is limited.',
                './resources/verticaltimeline')

            events_manager.add_handler(toggle_palette_cmd_def.commandCreated,
                        adsk.core.CommandCreatedEventHandler,
                        toggle_palette_command_created_handler)
        
        # Add the command to the View menu
        view_drop_down = get_view_drop_down()
        
        cntrl = view_drop_down.controls.itemById('thomasa88_showVerticalTimeline')
        if not cntrl:
            view_drop_down.controls.addCommand(toggle_palette_cmd_def,
                                               'SeparatorAfter_DashboardModeCloseCommand', False) 
        
        events_manager.add_handler(ui.commandTerminated,
                    adsk.core.ApplicationCommandEventHandler,
                    command_terminated_handler)

        # Edit command tracing
        # def f(args):
        #     print(args.commandId)
        #     args.isCanceled = True
        # events_manager.add_handler(ui.commandStarting,
        #             adsk.core.ApplicationCommandEventHandler,
        #             f)

        # Fusion bug: Activated is not called when switching to/from Drawing.
        # https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750
        events_manager.add_handler(app.documentActivated,
                    adsk.core.DocumentEventHandler,
                    document_activated_handler)

        events_manager.add_handler(ui.workspacePreDeactivate,
                    adsk.core.WorkspaceEventHandler,
                    workspace_pre_deactivate_handler)

        events_manager.add_handler(ui.workspaceActivated,
                    adsk.core.WorkspaceEventHandler,
                    workspace_activated_handler)

        print("Running")

        # Show palette when user starts the add-in manually
        if get_enabled() and app.isStartupComplete:
            show_palette()

def stop(context):
    with error_catcher:
        print('Stopping')

        events_manager.clean_up()

        # Delete the palette created by this add-in.
        palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')
        if palette:
            palette.deleteMe()

        # Delete controls and associated command definitions created by this add-ins
        view_drop_down = get_view_drop_down()
        cntrl = view_drop_down.controls.itemById('thomasa88_showVerticalTimeline')
        if cntrl:
            cntrl.deleteMe()
        cmdDef = ui.commandDefinitions.itemById('thomasa88_showVerticalTimeline')
        if cmdDef:
            cmdDef.deleteMe()

def toggle_palette_command_execute_handler(args):
    enable = not get_enabled()
    set_enabled(enable)
    if enable:
        if ui.activeWorkspace.id == 'FusionSolidEnvironment':
            show_palette()
        else:
            ui.messageBox('Vertical Timeline cannot be shown in this workspace. ' +
                        'It will be shown when you open a Design.')
    else:
        hide_palette()

def show_palette():
    global html_ready

    palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')
    if not palette:
        html_ready = False

        palette = ui.palettes.add('thomasa88_verticalTimelinePalette', f'Vertical Timeline v{manifest["version"]}',
                                    'palette.html',
                                    True, True, True, 250, 500, False)
        palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateLeft

        events_manager.add_handler(palette.incomingFromHTML,
                                   adsk.core.HTMLEventHandler,
                                   palette_incoming_from_html_handler)

        events_manager.add_handler(palette.closed,
                                   adsk.core.UserInterfaceGeneralEventHandler,
                                   palette_closed_handler)        
    else:
        invalidate()
        if not palette.isVisible:
            palette.isVisible = True

def hide_palette():
    palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')
    if palette:
        palette.isVisible = False

# Event handler for the commandCreated event.
def toggle_palette_command_created_handler(args):
    command = args.command
    events_manager.add_handler(command.execute,
                                adsk.core.CommandEventHandler,
                                toggle_palette_command_execute_handler)

# Event handler for the palette close event.
def palette_closed_handler(args):
    set_enabled(False)

# Event handler for the palette HTML event.                
def palette_incoming_from_html_handler(args):
    global html_ready
    htmlArgs = adsk.core.HTMLEventArgs.cast(args)
    action = htmlArgs.action
    data = json.loads(htmlArgs.data)
    html_commands = []
    if action == 'ready':
        print('HTML ready')
        html_ready = True

        # Cannot do sendInfoToHTML inside the event handler. We either have to use htmlArgs.returnData or
        # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
        html_commands.append(invalidate(send=False))
    elif action == 'setFeatureName':
        node = timeline_cache_map[data['id']]
        obj = node.obj
        visible_name = None
        if data['value'] != '':
            try:
                entity = obj.entity
            except RuntimeError:
                # Move and Align does not allow us to access their entity attribute
                entity = None
            if (not obj.isGroup
                and entity
                and entity.classType() == 'adsk::fusion::Occurrence'
                and thomasa88lib.timeline.get_occurrence_type(obj) != OCCURRENCE_BODIES_COMP):
                # Bonus of not doing a Command transaction: Undo history actually says from and to name.
                entity.component.name = data['value']
                # The shown name will have changed. Invalidate.
                #html_commands.append(invalidate(send=False))
            else:
                obj.name = data['value']
            visible_name = obj.name.lstrip()
        html_commands.append(visible_name)
    elif action == 'selectFeature' or action == 'editFeature':
        node = timeline_cache_map[data['id']]
        obj = node.obj
        ret = True

        design: adsk.fusion.Design = app.activeProduct
        entity = obj.entity

        # Making this in a transactory way so the current selection is not removed
        # if the entity is not selectable.
        newSelection = adsk.core.ObjectCollection.create()

        if isinstance(entity, adsk.fusion.Occurrence):
            associated_component = entity.sourceComponent
        elif isinstance(entity, adsk.fusion.ConstructionPlane):
            associated_component = entity.parent
        else:
            associated_component = entity.parentComponent

        if associated_component == design.rootComponent:
            # There are no occurrences of root. Just a single instance: root. Can select the entity directly.
            newSelection.add(entity)
        else:
            #Using _all_OccurrencesByComponent to get nested occurrences.
            in_occurrences = design.rootComponent.allOccurrencesByComponent(associated_component)
            if hasattr(entity, 'createForAssemblyContext'):
                for occurrence in in_occurrences:
                    proxy = entity.createForAssemblyContext(occurrence)
                    newSelection.add(proxy)
            elif hasattr(entity, 'bodies'):
                # Workaround for Feature objects
                ### TODO: Correctly select Feature objects. E.g. BoxFeature, CylinderFeature, ...
                ###       so that editing them works.
                for body in entity.bodies:
                    for occurrence in in_occurrences:
                        proxy = body.createForAssemblyContext(occurrence)
                        newSelection.add(proxy)

        try:
            ui.activeSelections.all = newSelection
        except Exception as e:
            ui.messageBox(f'Failed to select {thomasa88lib.utils.short_class(entity)}: {e}')
            ret = False
        
        if ret and action == 'editFeature':
            command_id = get_feature_edit_command_id(obj)
            if command_id:
                #print("T", ui.terminateActiveCommand())
                ui.commandDefinitions.itemById(command_id).execute()
            else:
                ui.messageBox(f'Editing {thomasa88lib.utils.short_class(entity)} feature is not supported')
                ret = False
        html_commands.append(ret)
    elif action == 'rollToFeature':
        node = timeline_cache_map[data['id']]
        obj = node.obj
        if obj.isGroup and not obj.isCollapsed:
            # Cannot move to collapsed group.
            # Move to the last item of the group.
            obj = obj[-1]
        elif not obj.isGroup and obj.parentGroup and obj.parentGroup.isCollapsed:
            # Cannot move to object inside collapsed group.
            # Move to the group instead.
            obj = obj.parentGroup
        html_commands.append(obj.rollTo(False))
        html_commands.append(invalidate(send=False))

    if html_commands:
        htmlArgs.returnData = json.dumps(html_commands)

def command_terminated_handler(args):
    eventArgs = adsk.core.ApplicationCommandEventArgs.cast(args)

    # As long as we don't update on command create, we only need to listen for command completion
    # Except Undo, which has a "Cancel" termination reason.
    if (eventArgs.terminationReason != adsk.core.CommandTerminationReason.CompletedTerminationReason and
        eventArgs.commandId != 'UndoCommand'):
        return

    # Helper to trace feature images
    #trace_feature_image(eventArgs)

    # Heavy traffic commands
    if eventArgs.commandId in ['SelectCommand', 'CommitCommand']:
        return
    
    invalidate()

def trace_feature_image(command_terminated_event_args):
    ''' Development function to trace feature images '''
    _, timeline = thomasa88lib.timeline.get_timeline()
    feature = None
    if timeline:
        try:
            feature = thomasa88lib.utils.short_class(timeline.item(timeline.count-1).entity)
        except Exception as e:
            feature = str(e)
    folder = command_terminated_event_args.commandDefinition.resourceFolder
    if folder:
        folder = folder.replace(thomasa88lib.utils.get_fusion_deploy_folder() + '/', '')
    print(f"'{feature}': ('{folder}', ''),")

#########################################################################################
# app.product is not ready at workspaceActivated, but documentActivated does not fire
# when switching to/from Drawing. However, in that case, it seems that the product is
# ready when we call thomasa88lib.timeline.get_timeline (presumably since the panel has to be recreated)
# Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750
#
# PLM360OpenAttachmentCommand + MarkDocumentsForOpenCommand could possibly be used as
# another workaround.
#
# Event order:
# DocumentActivating
# OnWorkspaceActivated
# DocumentActivated
# PLM360OpenAttachmentCommand or MarkDocumentsForOpenCommand
#

def workspace_pre_deactivate_handler(args):
    #eventArgs = adsk.core.DocumentEventArgs.cast(args)
    if get_enabled():
        invalidate(clear=True)

def workspace_activated_handler(args):
    #eventArgs = adsk.core.WorkspaceEventArgs.cast(args)

    if ui.activeWorkspace.id == 'FusionSolidEnvironment':
        if get_enabled():
            show_palette()
    else:
        # Deactivate
        hide_palette()

def document_activated_handler(args):
    #eventArgs = adsk.core.DocumentEventArgs.cast(args)
    if ui.activeWorkspace.id == 'FusionSolidEnvironment':
        if get_enabled():
            show_palette()

#########################################################################################