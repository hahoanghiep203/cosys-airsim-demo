#include "UnrealImageCapture.h"
#include "Engine/World.h"
#include "ImageUtils.h"


#include "SyntheticCameraProcessor.h"
#include "AirBlueprintLib.h"

#include "RenderRequest.h"
#include "common/ClockFactory.hpp"

UnrealImageCapture::UnrealImageCapture(const common_utils::UniqueValueMap<std::string, APIPCamera*>* cameras)
    : cameras_(cameras)
{
    //TODO: explore screenshot option
    //addScreenCaptureHandler(camera->GetWorld());
}

UnrealImageCapture::~UnrealImageCapture()
{
}

void UnrealImageCapture::getImages(
    const std::vector<msr::airlib::ImageCaptureBase::ImageRequest>& requests,
    std::vector<msr::airlib::ImageCaptureBase::ImageResponse>& responses) const
{
    // No cameras available
    if (cameras_->valsSize() == 0) {
        for (unsigned int i = 0; i < requests.size(); ++i) {
            responses.push_back(ImageResponse());
            responses.back().message = "camera is not set";
        }
        return;
    }

    // Check whether this batch contains a synthetic ThermalIR request
    bool has_thermal = false;

    for (const auto& request : requests) {
        if (request.image_type == ImageType::ThermalIR) {
            has_thermal = true;
            break;
        }
    }

    // Normal Cosys-AirSim path: nothing changes
    if (!has_thermal) {
        getSceneCaptureImage(requests, responses, false);
        return;
    }

    // ThermalIR does not own a SceneCaptureComponent.
    // It is synthesized from:
    //
    //     Segmentation RGB
    //          +
    //     DepthPlanar float
    //          ↓
    // SyntheticCameraProcessor
    //          ↓
    //       ThermalIR
    //
    // Build one combined render batch so the hidden captures
    // come from the same simulation frame.

    std::vector<ImageRequest> render_requests;

    struct Slot
    {
        bool thermal = false;

        size_t normal_idx = 0;

        size_t segmentation_idx = 0;
        size_t depth_idx = 0;
        size_t lighting_idx = 0;
        size_t normals_idx = 0;
    };

    std::vector<Slot> slots(requests.size());

    // --------------------------------------------------------
    // Pass 1:
    // Forward all normal image requests unchanged.
    // --------------------------------------------------------
    for (size_t i = 0; i < requests.size(); ++i) {

        const ImageRequest& request = requests.at(i);

        if (request.image_type == ImageType::ThermalIR)
            continue;

        render_requests.push_back(request);
        slots[i].normal_idx = render_requests.size() - 1;
    }

    // --------------------------------------------------------
    // Helper:
    // Re-use an identical hidden request if one already exists.
    // --------------------------------------------------------
    auto find_or_append =
        [&render_requests](
            const std::string& camera_name,
            ImageType image_type,
            bool pixels_as_float) -> size_t
    {
        for (size_t j = 0; j < render_requests.size(); ++j) {

            const ImageRequest& existing = render_requests[j];

            if (existing.camera_name == camera_name &&
                existing.image_type == image_type &&
                existing.pixels_as_float == pixels_as_float &&
                (pixels_as_float || !existing.compress) &&
                existing.annotation_name.empty())
            {
                return j;
            }
        }

        render_requests.push_back(
            ImageRequest(
                camera_name,
                image_type,
                pixels_as_float,
                false,
                ""
            )
        );

        return render_requests.size() - 1;
    };

    // --------------------------------------------------------
    // Pass 2:
    // Convert each ThermalIR request into two hidden requests.
    // --------------------------------------------------------
    for (size_t i = 0; i < requests.size(); ++i) {

        const ImageRequest& request = requests.at(i);

        if (request.image_type == ImageType::ThermalIR) {

            slots[i].thermal = true;

            slots[i].segmentation_idx =
                find_or_append(
                    request.camera_name,
                    ImageType::Segmentation,
                    false
                );

            slots[i].depth_idx =
                find_or_append(
                    request.camera_name,
                    ImageType::DepthPlanar,
                    true
                );
            slots[i].lighting_idx =
                find_or_append(
                    request.camera_name,
                    ImageType::Lighting,
                    false
                );
            slots[i].normals_idx =
                find_or_append(
                    request.camera_name,
                    ImageType::SurfaceNormals,
                    false
                );
        }
    }

    // --------------------------------------------------------
    // Render Segmentation + DepthPlanar + normal images
    // in one batch.
    // --------------------------------------------------------
    std::vector<ImageResponse> render_responses;

    getSceneCaptureImage(
        render_requests,
        render_responses,
        false
    );

    if (render_responses.size() != render_requests.size()) {
        return;
    }

    // --------------------------------------------------------
    // Reconstruct responses in the exact order requested
    // by the user.
    // --------------------------------------------------------
    for (size_t i = 0; i < requests.size(); ++i) {

        const ImageRequest& request = requests.at(i);

        // Normal image request
        if (!slots[i].thermal) {

            responses.push_back(
                render_responses.at(
                    slots[i].normal_idx
                )
            );

            continue;
        }

        // Thermal hidden captures
        const ImageResponse& segmentation_response =
            render_responses.at(
                slots[i].segmentation_idx
            );

        const ImageResponse& depth_response =
            render_responses.at(
                slots[i].depth_idx
            );
        const ImageResponse& lighting_response =
            render_responses.at(
                slots[i].lighting_idx
            );
        const ImageResponse& normals_response =
            render_responses.at(
                slots[i].normals_idx
            );

        ImageResponse response;

        response.camera_name = request.camera_name;
        response.image_type = request.image_type;

        // Thermal output is RGB uint8, not float depth
        response.pixels_as_float = false;
        response.annotation_name = "";

        response.width =
            segmentation_response.width;

        response.height =
            segmentation_response.height;

        response.time_stamp =
            segmentation_response.time_stamp;

        response.camera_position =
            segmentation_response.camera_position;

        response.camera_orientation =
            segmentation_response.camera_orientation;

        const size_t expected_segmentation_size =
            static_cast<size_t>(
                segmentation_response.width
            )
            *
            static_cast<size_t>(
                segmentation_response.height
            )
            * 3;

        std::vector<uint8_t> thermal_rgb;

        if (expected_segmentation_size == 0) {

            response.message =
                "Can't compose ThermalIR because underlying captures failed";
        }
        else if (
            segmentation_response.image_data_uint8.size()
            != expected_segmentation_size)
        {
            response.message =
                "Can't compose ThermalIR because segmentation capture failed";
        }
        else {

            SyntheticCameraProcessor::instance()
                .composeThermalIR(
                    segmentation_response.image_data_uint8,
                    depth_response.image_data_float,
                    lighting_response.image_data_uint8,
                    normals_response.image_data_uint8,
                    segmentation_response.width,
                    segmentation_response.height,
                    thermal_rgb
                );
        }

        // ----------------------------------------------------
        // Optional PNG compression
        // ----------------------------------------------------
        if (!thermal_rgb.empty() && request.compress) {

            TArray<FColor> bitmap;

            bitmap.SetNumUninitialized(
                response.width * response.height
            );

            for (int32 p = 0;
                 p < response.width * response.height;
                 ++p)
            {
                bitmap[p] = FColor(
                    thermal_rgb[p * 3 + 0],
                    thermal_rgb[p * 3 + 1],
                    thermal_rgb[p * 3 + 2],
                    255
                );
            }

            TArray<uint8_t> png;

            UAirBlueprintLib::CompressImageArray(
                response.width,
                response.height,
                bitmap,
                png
            );

            response.image_data_uint8 =
                std::vector<uint8_t>(
                    png.GetData(),
                    png.GetData() + png.Num()
                );

            response.compress = true;
        }
        else {

            response.image_data_uint8 =
                std::move(thermal_rgb);

            response.compress = false;
        }

        responses.push_back(
            std::move(response)
        );
    }
}

void UnrealImageCapture::getSceneCaptureImage(const std::vector<msr::airlib::ImageCaptureBase::ImageRequest>& requests,
                                              std::vector<msr::airlib::ImageCaptureBase::ImageResponse>& responses, bool use_safe_method) const
{
    std::vector<std::shared_ptr<RenderRequest::RenderParams>> render_params;
    std::vector<std::shared_ptr<RenderRequest::RenderResult>> render_results;

    

    bool visibilityChanged = false;
    for (unsigned int i = 0; i < requests.size(); ++i) {
        APIPCamera* camera = cameras_->at(requests.at(i).camera_name);
        //TODO: may be we should have these methods non-const?
        if (requests[i].image_type == ImageType::Annotation) {
            if (camera->GetAnnotationNameExist(requests[i].annotation_name)){
                visibilityChanged = const_cast<UnrealImageCapture*>(this)->updateCameraVisibility(camera, requests[i]) || visibilityChanged;
			}
        }
        else {
            visibilityChanged = const_cast<UnrealImageCapture*>(this)->updateCameraVisibility(camera, requests[i]) || visibilityChanged;
        }
    }

    if (use_safe_method && visibilityChanged) {
        // We don't do game/render thread synchronization for safe method.
        // We just blindly sleep for 200ms (the old way)
        std::this_thread::sleep_for(std::chrono::duration<double>(0.2));
    }

    UGameViewportClient* gameViewport = nullptr;
    for (unsigned int i = 0; i < requests.size(); ++i) {

        APIPCamera* camera = cameras_->at(requests.at(i).camera_name);

        if (gameViewport == nullptr) {
            gameViewport = camera->GetWorld()->GetGameViewport();
        }

        responses.push_back(ImageResponse());
        ImageResponse& response = responses.at(i);          
        UTextureRenderTarget2D* textureTarget = nullptr;
        USceneCaptureComponent2D* capture = nullptr;
        if (requests[i].image_type == ImageType::Annotation) {
            if (camera->GetAnnotationNameExist(requests[i].annotation_name)) {
                capture = camera->getCaptureComponent(requests[i].image_type, false, requests[i].annotation_name);
                if (capture == nullptr) {
                    response.message = "Can't take screenshot because none camera type is not active";
                }
                else if (capture->TextureTarget == nullptr) {
                    response.message = "Can't take screenshot because texture target is null";
                }
                else
                    textureTarget = capture->TextureTarget;
            }
            else {
                response.message = "Can't take screenshot because none annotation name does not exist for this camera";
            }
        }
        else {
            capture = camera->getCaptureComponent(requests[i].image_type, false, requests[i].annotation_name);
            if (capture == nullptr) {
                response.message = "Can't take screenshot because none camera type is not active";
            }
            else if (capture->TextureTarget == nullptr) {
                response.message = "Can't take screenshot because texture target is null";
            }
            else
                textureTarget = capture->TextureTarget;
        }
        
        bool disable_gamma = false;
        if (requests[i].image_type == ImageCaptureBase::ImageType::Segmentation || requests[i].image_type == ImageCaptureBase::ImageType::Annotation)disable_gamma = true;
        render_params.push_back(std::make_shared<RenderRequest::RenderParams>(capture, textureTarget, requests[i].pixels_as_float, requests[i].compress, disable_gamma));
    }

    if (nullptr == gameViewport) {
        return;
    }

    auto query_camera_pose_cb = [this, &requests, &responses]() {
        size_t count = requests.size();
        for (size_t i = 0; i < count; i++) {
            const ImageRequest& request = requests.at(i);
            APIPCamera* camera = cameras_->at(request.camera_name);
            ImageResponse& response = responses.at(i);
            auto camera_pose = camera->getPose();
            response.camera_position = camera_pose.position;
            response.camera_orientation = camera_pose.orientation;
        }
    };
    RenderRequest render_request{ gameViewport, std::move(query_camera_pose_cb) };

    render_request.getScreenshot(render_params.data(), render_results, render_params.size(), use_safe_method);

    for (unsigned int i = 0; i < requests.size(); ++i) {
        const ImageRequest& request = requests.at(i);
        ImageResponse& response = responses.at(i);

        response.camera_name = request.camera_name;
        response.time_stamp = render_results[i]->time_stamp;
        response.image_data_uint8 = std::vector<uint8_t>(render_results[i]->image_data_uint8.GetData(), render_results[i]->image_data_uint8.GetData() + render_results[i]->image_data_uint8.Num());
        response.image_data_float = std::vector<float>(render_results[i]->image_data_float.GetData(), render_results[i]->image_data_float.GetData() + render_results[i]->image_data_float.Num());

        if (use_safe_method) {
            // Currently, we don't have a way to synthronize image capturing and camera pose when safe method is used,
            APIPCamera* camera = cameras_->at(request.camera_name);
            msr::airlib::Pose pose = camera->getPose();
            response.camera_position = pose.position;
            response.camera_orientation = pose.orientation;
        }
        response.pixels_as_float = request.pixels_as_float;
        response.compress = request.compress;
        response.width = render_results[i]->width;
        response.height = render_results[i]->height;
        response.image_type = request.image_type;
		response.annotation_name = request.annotation_name;
    }
}

bool UnrealImageCapture::updateCameraVisibility(APIPCamera* camera, const msr::airlib::ImageCaptureBase::ImageRequest& request)
{
    bool visibilityChanged = false;
    if (!camera->getCameraTypeEnabled(request.image_type, request.annotation_name)) {
        camera->setCameraTypeEnabled(request.image_type, true, request.annotation_name);
        visibilityChanged = true;
    }

    return visibilityChanged;
}

bool UnrealImageCapture::getScreenshotScreen(ImageType image_type, std::vector<uint8_t>& compressedPng)
{
    FScreenshotRequest::RequestScreenshot(false); // This is an async operation
    return true;
}

void UnrealImageCapture::addScreenCaptureHandler(UWorld* world)
{
    static bool is_installed = false;

    if (!is_installed) {
        UGameViewportClient* ViewportClient = world->GetGameViewport();
        ViewportClient->OnScreenshotCaptured().Clear();
        ViewportClient->OnScreenshotCaptured().AddLambda(
            [this](int32 SizeX, int32 SizeY, const TArray<FColor>& Bitmap) {
                // Make sure that all alpha values are opaque.
                TArray<FColor>& RefBitmap = const_cast<TArray<FColor>&>(Bitmap);
                for (auto& Color : RefBitmap)
                    Color.A = 255;

                TArray<uint8_t> last_compressed_png;
                FImageUtils::CompressImageArray(SizeX, SizeY, RefBitmap, last_compressed_png);
                last_compressed_png_ = std::vector<uint8_t>(last_compressed_png.GetData(), last_compressed_png.GetData() + last_compressed_png.Num());
            });

        is_installed = true;
    }
}
