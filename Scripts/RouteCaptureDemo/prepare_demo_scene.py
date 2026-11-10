"""Build the project-local example map in the isolated editor."""
import math
import unreal

MAP='/Game/RouteCapture/Maps/RouteCaptureDemo'
unreal.EditorAssetLibrary.make_directory('/Game/RouteCapture/Maps')
if unreal.EditorAssetLibrary.does_asset_exist(MAP):
    if not unreal.EditorLevelLibrary.load_level(MAP):
        raise RuntimeError('Cannot load the existing example level')
else:
    if not unreal.EditorLevelLibrary.new_level(MAP):
        raise RuntimeError('Cannot create the example level')

actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
for actor in list(actors.get_all_level_actors()):
    if actor.get_actor_label().startswith('RouteDemo_'):
        actors.destroy_actor(actor)

def spawn(cls, name, position, rotation=(0,0,0)):
    actor=actors.spawn_actor_from_class(cls,unreal.Vector(*position),unreal.Rotator(*rotation))
    if not actor: raise RuntimeError('Cannot spawn '+name)
    actor.set_actor_label('RouteDemo_'+name)
    return actor

floor=spawn(unreal.StaticMeshActor,'Ground',(0,0,-10))
floor.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Cube'))
floor.set_actor_scale3d(unreal.Vector(40,40,.2))
sun=spawn(unreal.DirectionalLight,'Sun',(0,0,1200),(-50,-30,0))
sun.light_component.set_editor_property('intensity',5)
sun.light_component.set_editor_property('mobility',unreal.ComponentMobility.MOVABLE)
try: sun.light_component.set_editor_property('atmosphere_sun_light',True)
except Exception: pass
sky=spawn(unreal.SkyLight,'SkyLight',(0,0,800))
sky.light_component.set_editor_property('intensity',.8)
sky.light_component.set_editor_property('mobility',unreal.ComponentMobility.MOVABLE)
spawn(unreal.SkyAtmosphere,'Atmosphere',(0,0,0))
spawn(unreal.PlayerStart,'PlayerStart',(0,0,100))
observer_position=unreal.Vector(-1900,-2100,1500)
observer_rotation=unreal.MathLibrary.find_look_at_rotation(observer_position,unreal.Vector(0,0,180))
observer=spawn(unreal.SceneCapture2D,'Observer',observer_position.to_tuple(),observer_rotation.to_tuple())
observer.get_editor_property('capture_component2d').set_editor_property('capture_every_frame',False)
observer.get_editor_property('capture_component2d').set_editor_property('capture_on_movement',False)
car_cls=unreal.load_class(None,'/Game/Thermal/Blueprints/BP_ThermalHatchback.BP_ThermalHatchback_C')
if not car_cls: raise RuntimeError('Thermal Hatchback Blueprint is missing')
car=spawn(car_cls,'ThermalCar',(0,0,0))
mode=unreal.load_class(None,'/Script/AirSim.AirSimGameMode')
world.get_world_settings().set_editor_property('default_game_mode',mode)
route_cls=unreal.load_class(None,'/Script/AirSimRouteCapture.DroneCaptureRoute')
if not route_cls: raise RuntimeError('Build the Route Capture plugin first')
route=spawn(route_cls,'Route',(0,0,0))
route.set_editor_property('json_file',str(ROOT/'Config/RouteCapture/at_nodes.json'))
if not route.import_mission(): raise RuntimeError('Native mission import failed: '+str(route.get_editor_property('status')))
point_cls=unreal.load_class(None,'/Script/AirSimRouteCapture.DroneRoutePoint')
points=unreal.GameplayStatics.get_all_actors_of_class(world,point_cls)
for point in points:
    point.set_editor_property('demo_visible_in_game',True)
    point.get_editor_property('direction').set_hidden_in_game(False)
    point.get_editor_property('number').set_hidden_in_game(False)

# Demo-only ground guides are excluded from all drone cameras by their tag.
assets=unreal.AssetToolsHelpers.get_asset_tools()
material_path='/Game/RouteCapture/Materials/M_DemoGuide'
unreal.EditorAssetLibrary.make_directory('/Game/RouteCapture/Materials')
material=unreal.load_asset(material_path)
if not material:
    material=assets.create_asset('M_DemoGuide','/Game/RouteCapture/Materials',unreal.Material,unreal.MaterialFactoryNew())
    color=unreal.MaterialEditingLibrary.create_material_expression(material,unreal.MaterialExpressionConstant3Vector,0,0)
    color.set_editor_property('constant',unreal.LinearColor(.01,.7,.9,1))
    unreal.MaterialEditingLibrary.connect_material_property(color,'',unreal.MaterialProperty.MP_BASE_COLOR)
    unreal.MaterialEditingLibrary.connect_material_property(color,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material)
positions=[(-600,-600,250),(600,-600,250),(600,600,250),(-600,600,250)]
for i,position in enumerate(positions):
    guide=spawn(unreal.StaticMeshActor,'NodeGuide'+str(i+1),(position[0],position[1],5))
    guide.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Cylinder'))
    guide.set_actor_scale3d(unreal.Vector(1,1,.05))
    guide.static_mesh_component.set_material(0,material)
    guide.set_actor_enable_collision(False)
    guide.set_editor_property('tags',[unreal.Name('RouteCaptureMarker'),unreal.Name('ThermalIgnore')])
for i,(a,b) in enumerate(zip(positions[:-1],positions[1:])):
    midpoint=unreal.Vector((a[0]+b[0])/2,(a[1]+b[1])/2,3)
    yaw=math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))
    guide=spawn(unreal.StaticMeshActor,'SegmentGuide'+str(i+1),midpoint.to_tuple(),(0,yaw,0))
    guide.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Cube'))
    guide.set_actor_scale3d(unreal.Vector(math.hypot(b[0]-a[0],b[1]-a[1])/100,.08,.03))
    guide.static_mesh_component.set_material(0,material)
    guide.set_actor_enable_collision(False)
    guide.set_editor_property('tags',[unreal.Name('RouteCaptureMarker'),unreal.Name('ThermalIgnore')])
route.refresh_preview()
if not unreal.EditorLevelLibrary.save_current_level(): raise RuntimeError('Cannot save the example map')
result={'map':MAP,'route':route.get_name(),'car':car.get_name(),'points':len(points),'validation':route.validate_route()}
