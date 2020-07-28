#Author-Thomas Axelsson
#Description-Provides a vertical timeline.

# Put add-in folder in %appdata%\Autodesk\Autodesk Fusion 360\API\AddIns

# Need to use Visual Studio Code Python extension version 2019.9.34911
# to be able to debug with Fusion.. (2020-07-23)

import adsk.core, adsk.fusion, adsk.cam, traceback

from collections import defaultdict
import json
import os
import threading

# global set of event handlers to keep them referenced for the duration of the command
handlers = []

ui = None
app = None
onCommandTerminated = None

html_ready = False

watcher_thread = None
watcher_event = None
watcher_stop_flag = None
timeline_item_count = 0

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'settings.json')

# Occurrence types
OCCURRENCE_UNKNOWN_COMP = 0
OCCURRENCE_NEW_COMP = 1
OCCURRENCE_COPY_COMP = 2
OCCURRENCE_SHEET_METAL = 3
OCCURRENCE_BODIES_COMP = 4

TIMELINE_STATUS_OK = 0
TIMELINE_STATUS_PRODUCT_NOT_READY = 1
TIMELINE_STATUS_NOT_PARAMETRIC = 2

_settings = None
def getEnabled():
    global _settings
    if _settings is None:
        try:
            with open(SETTINGS_FILE, 'r') as f:
                _settings = json.load(f)
        except FileNotFoundError:
            _settings = {}
            _settings['enabled'] = False
    return _settings['enabled']

def setEnabled(value):
    global _settings
    if _settings is None:
        _settings = {}
    _settings['enabled'] = value
    with open(SETTINGS_FILE, 'w+') as f:
        json.dump(_settings, f)

def get_timeline():
    product = app.activeProduct
    if product is None or product.classType() != 'adsk::fusion::Design':
        print("get_timeline: Product not ready")
        return (TIMELINE_STATUS_PRODUCT_NOT_READY, None)
    
    design = adsk.fusion.Design.cast(product)

    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        return (TIMELINE_STATUS_OK, design.timeline)
    else:
        return (TIMELINE_STATUS_NOT_PARAMETRIC, None)

def get_occurrence_type(obj):
    # Heuristics to determine component creation feature
    
    # When prefixed with a "type prefix", we can be sure of the occurence type
    # In this case, the name of the timeline object cannot be edited
    # This, of course, assumes that the user does not create a component starting
    # with such a string.
    split_name = obj.name.split(' ', maxsplit=1)
    # User can have input spaces, so a length of split_name > 1 does not automatically
    # mean that we have a type prefix. So let's try.
    # TODO: We can probably compare with the component name to find out if this is
    #       indeed a prefix.
    potential_type_prefix = split_name[0]
    if potential_type_prefix == '':
        return OCCURRENCE_NEW_COMP
        # I have not found ant way to determine if a component is a sheet metal component.
        # Solid features are allowed in sheet metal components and sheet metal features are
        # allowed in "normal" components, so cannot use the content as a differentiator.
        #return OCCURRENCE_SHEET_METAL
    if potential_type_prefix == 'CopyPaste':
        return OCCURRENCE_COPY_COMP

    if hasattr(obj.entity, 'bRepBodies'):
        return OCCURRENCE_BODIES_COMP

    return OCCURRENCE_UNKNOWN_COMP

        # if obj.entity.bRepBodies.count == 0:
        #     return OCCURRENCE_SHEET_METAL
        # else:

def short_class(obj):
    return obj.classType().split('::')[-1]

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
    'Occurrence': lambda i: OCCURRENCE_RESOURCE_MAP[get_occurrence_type(i)],
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
    'ConstructionPlane': lambda i: PLANE_RESOURCE_MAP.get(short_class(i.entity.definition)),
    
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
    fusionType = short_class(entity)
    match = FEATURE_RESOURCE_MAP.get(fusionType)
    if callable(match):
        match = match(obj)
    return match

def get_image_path(subpath):
    path = f'{get_product_deploy_folder()}/{subpath}/16x16.png'
    if os.path.exists(path):
        return path
    else:
        print(f'File does not exist: {path}')
        return None

_resFolder = None
def get_resource_folder():
    global _resFolder
    if not _resFolder:
        _resFolder = ui.workspaces.itemById('FusionSolidEnvironment').resourceFolder.replace('/Environment/Model', '')
    return _resFolder

def get_product_deploy_folder():
    return get_resource_folder().replace('/Fusion/UI/FusionUI/Resources', '')

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
    global html_ready

    palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')

    if not palette or not html_ready:
        return

    message = ""
    features = []
    max_parents = 0
    if not clear:
        timeline_status, timeline = get_timeline()
        if timeline_status == TIMELINE_STATUS_OK:
            timeline_item_count = timeline.count
            features, max_parents = get_features(timeline)
        elif timeline_status == TIMELINE_STATUS_PRODUCT_NOT_READY:
            timeline_item_count = -1
        elif timeline_status == TIMELINE_STATUS_NOT_PARAMETRIC:
            timeline_item_count = -1
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
    flat_timeline = get_flat_timeline(timeline)
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
            'suppressed': obj.isSuppressed or obj.isRolledBack,
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
                feature['type'] = short_class(obj.entity)
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
                if get_occurrence_type(obj) != OCCURRENCE_BODIES_COMP:
                    # Name is a read-only instance variant of the component's name,
                    # with a prefix on it.
                    # Let the user modify the component's name instead
                    feature['edit-name'] = obj.entity.component.name

        features.append(feature)

    return (features, max_parents)

def get_feature_parent_path(component_parent_map, obj):
    design = app.activeProduct

    feature = obj.entity
    feature_type = short_class(feature)
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

def get_flat_timeline(timeline_collection):
    '''A flat timeline representation, with all objects except any group objects.'''
    flat_collection = []
    
    for i, obj in enumerate(timeline_collection):
        if obj.isGroup:
            # Groups only appear in the timeline if they are collapsed
            # In that case, the features inside the group are only listed within the group
            # and not as part of the top-level timeline. So timeline essentially gives us
            # what is literally shown in the timeline control in Fusion.

            # Flatten the group
            flat_collection += get_flat_timeline(obj)
        else:
            flat_collection.append(obj)

    return flat_collection

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

def error_catcher_wrapper(func):
    def catcher(self, args):
        try:
            func(args)
        except:
            print('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))
            if ui:
                ui.messageBox(f'Vertical Timeline failed:\n{traceback.format_exc()}')
    return catcher

def add_handler(event, base_class, notify_callback):
    handler_name = base_class.__name__ + 'Handler'
    handler_class = type(handler_name, (base_class,),
                         { "notify": error_catcher_wrapper(notify_callback) })
    handler_class.__init__ = lambda self: super(handler_class, self).__init__()
    handler = handler_class()
    # Avoid garbage collection
    handlers.append((handler, event))
    event.add(handler)

def get_view_drop_down():
    qat = ui.toolbars.itemById('QAT')
    file_drop_down = qat.controls.itemById('FileSubMenuCommand')
    view_drop_down = file_drop_down.controls.itemById('ViewWidgetCommand')
    return view_drop_down

def start_watcher():
    global watcher_stop_flag
    global watcher_event # Avoid garbage collection
    global watcher_thread
    watcher_stop_flag = threading.Event()
    watcher_event = app.registerCustomEvent('thomasa88_timelineWatch')
    add_handler(watcher_event,
                adsk.core.CustomEventHandler,
                lambda args: check_timeline())
    watcher_thread = threading.Thread(target=watcher_runner)
    watcher_thread.start()

def stop_watcher():
    watcher_stop_flag.set()
    app.unregisterCustomEvent('thomasa88_timelineWatch')

    # GUI will be frozen during wait
    watcher_thread.join(timeout=3)
    if watcher_thread.is_alive():
        ui.messageBox('Vertical Timeline watcher did not stop!')

def watcher_runner():
    global watcher_stop_flag
    while not watcher_stop_flag.wait(1):
        app.fireCustomEvent('thomasa88_timelineWatch')

def check_timeline():
    global timeline_item_count
    global html_ready
    timeline_status, timeline = get_timeline()
    if timeline_status == TIMELINE_STATUS_OK:
        if timeline.count != timeline_item_count:
            invalidate()
    else:
        timeline_item_count = -1

def run(context):
    global ui, app, handlers
    debug = False
    try:
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
                '')

            add_handler(toggle_palette_cmd_def.commandCreated,
                        adsk.core.CommandCreatedEventHandler,
                        toggle_palette_command_created_handler)
        
        # Add the command to the View menu
        view_drop_down = get_view_drop_down()
        
        cntrl = view_drop_down.controls.itemById('thomasa88_showVerticalTimeline')
        if not cntrl:
            view_drop_down.controls.addCommand(toggle_palette_cmd_def,
                                               'SeparatorAfter_DashboardModeCloseCommand', False) 
        
        add_handler(ui.commandTerminated,
                    adsk.core.ApplicationCommandEventHandler,
                    command_terminated_handler)

        # Edit command tracing
        # def f(args):
        #     print(args.commandId)
        #     args.isCanceled = True
        # add_handler(ui.commandStarting,
        #             adsk.core.ApplicationCommandEventHandler,
        #             f)

        # Fusion bug: Activated is not called when switching to/from Drawing.
        # https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750
        add_handler(app.documentActivated,
                    adsk.core.DocumentEventHandler,
                    document_activated_handler)

        add_handler(ui.workspacePreDeactivate,
                    adsk.core.WorkspaceEventHandler,
                    workspace_pre_deactivate_handler)

        add_handler(ui.workspaceActivated,
                    adsk.core.WorkspaceEventHandler,
                    workspace_activated_handler)                

        start_watcher()

        print("Running")

        if getEnabled():
            show_palette()
    except:
        print('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))
        if ui and not debug:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))

def stop(context):
    try:
        print('Stopping')

        stop_watcher()

        for handler, event in handlers:
            event.remove(handler)
        handlers.clear()

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
    except:
        if ui:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))


class TogglePaletteCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            enable = not getEnabled()
            setEnabled(enable)
            if enable:
                if ui.activeWorkspace.id == 'FusionSolidEnvironment':
                    show_palette()
                else:
                    ui.messageBox('Vertical Timeline cannot be shown in this workspace. ' +
                                'It will be shown when you open a Design.')
            else:
                hide_palette()
        except:
            ui.messageBox('Command executed Vertical Timeline failed: {}'.format(traceback.format_exc()))

def show_palette():
    global html_ready

    palette = ui.palettes.itemById('thomasa88_verticalTimelinePalette')
    if not palette:
        html_ready = False

        palette = ui.palettes.add('thomasa88_verticalTimelinePalette', 'Vertical Timeline', 'palette.html',
                                    True, True, True, 250, 500, False)
        palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateLeft

        onHTMLEvent = HTMLEventHandler()
        palette.incomingFromHTML.add(onHTMLEvent)   
        handlers.append((onHTMLEvent, palette.incomingFromHTML))

        onClosed = CloseEventHandler()
        palette.closed.add(onClosed)
        handlers.append((onClosed, palette.closed))
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
        onExecute = TogglePaletteCommandExecuteHandler()
        command.execute.add(onExecute)
        handlers.append((onExecute, command.execute))

# Event handler for the palette close event.
class CloseEventHandler(adsk.core.UserInterfaceGeneralEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            setEnabled(False)
        except:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))

# Event handler for the palette HTML event.                
class HTMLEventHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        global html_ready
        try:
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
                        and get_occurrence_type(obj) != OCCURRENCE_BODIES_COMP):
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

                if obj.isSuppressed:
                    ui.messageBox('Cannot select suppressed features')
                    ret = False
                elif obj.isRolledBack:
                    ui.messageBox('Cannot select rolled back features')
                    ret = False
                else:
                    # Making this in a transactory way so the current selection is not removed
                    # if the entity is not selectable.
                    newSelection = adsk.core.ObjectCollection.create()
                    newSelection.add(obj.entity)
                    try:
                        ui.activeSelections.all = newSelection
                    except Exception as e:
                        ui.messageBox(f'Failed to select this entity: {e}')
                        ret = False
                    
                    if ret and action == 'editFeature':
                        command_id = get_feature_edit_command_id(obj)
                        if command_id:
                            #print("T", ui.terminateActiveCommand())
                            ui.commandDefinitions.itemById(command_id).execute()
                        else:
                            ui.messageBox(f'Editing {short_class(obj.entity)} feature is not supported')
                            ret = False
                html_commands.append(ret)
            if html_commands:
                htmlArgs.returnData = json.dumps(html_commands)
        except:
            ui.messageBox('Vertical Timeline failed:\n{}'.format(traceback.format_exc()))   

class CommandTerminationReason:
    UnknownTerminationReason = 0
    CompletedTerminationReason = 1
    CancelledTerminationReason = 2
    AbortedTerminationReason = 3
    PreEmptedTerminationReason = 4
    SessionEndingTerminationReason = 5


def command_terminated_handler(args):
    eventArgs = adsk.core.ApplicationCommandEventArgs.cast(args)

    # As long as we don't update on command create, we only need to listen for command completion
    if eventArgs.terminationReason != CommandTerminationReason.CompletedTerminationReason:
        return

    # Helper to trace feature images
    #trace_feature_image(eventArgs)

    # Heavy traffic commands
    if eventArgs.commandId in ['SelectCommand', 'CommitCommand']:
        return
    
    invalidate()

def trace_feature_image(command_terminated_event_args):
    ''' Development function to trace feature images '''
    _, timeline = get_timeline()
    feature = None
    if timeline:
        try:
            feature = short_class(timeline.item(timeline.count-1).entity)
        except Exception as e:
            feature = str(e)
    folder = command_terminated_event_args.commandDefinition.resourceFolder
    if folder:
        folder = folder.replace(get_product_deploy_folder() + '/', '')
    print(f"'{feature}': ('{folder}', ''),")

#########################################################################################
# app.product is not ready at workspaceActivated, but documentActivated does not fire
# when switching to/from Drawing. However, in that case, it seems that the product is
# ready when we call get_timeline (presumably since the panel has to be recreated)
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
    if getEnabled():
        invalidate(clear=True)

def workspace_activated_handler(args):
    #eventArgs = adsk.core.WorkspaceEventArgs.cast(args)

    if ui.activeWorkspace.id == 'FusionSolidEnvironment':
        if getEnabled():
            show_palette()
    else:
        # Deactivate
        hide_palette()

def document_activated_handler(args):
    #eventArgs = adsk.core.DocumentEventArgs.cast(args)
    if ui.activeWorkspace.id == 'FusionSolidEnvironment':
        if getEnabled():
            show_palette()

#########################################################################################