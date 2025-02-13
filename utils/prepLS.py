
import uuid
import requests
import glob
import os
import logging
from dateutil.parser import parse
import tarfile
from utils.prep_utils import *
from typing import List


def download_scene(landsat_download_url: str, target_folder: str = "/tmp/data/download"):
    # download the tar.gz file from the landsat download url into the target folder and
    # return filenames from the tar.gz file
    logging.info(f"Downloading scene from {landsat_download_url}")
    logging.info(f"Target folder is {target_folder}")
    tar_path = os.path.join(
        target_folder, os.path.basename(landsat_download_url))
    get_file_via_stream(landsat_download_url, tar_path)
    logging.info(f"Downloaded scene from {landsat_download_url}")
    logging.info(f"Target folder is {target_folder}")
    logging.info(f"Tar file is {tar_path}")
    tar = tarfile.open(tar_path)
    files_in_tar = tar.getnames()
    logging.info(f"Files in tar are {files_in_tar}")
    return tar_path, files_in_tar


def extract_scene(scene_path, target_folder):
    # extract the tar.gz file into the target folder
    logging.info(f"Extracting scene from {scene_path} to {target_folder}")
    tar = tarfile.open(scene_path)
    tar.extractall(target_folder)
    logging.info(f"Extracted scene from {scene_path} to {target_folder}")
    return target_folder


# def download_extract_ls_url(ls_url, down_tar, untar_dir):
#
#     if not os.listdir(untar_dir):
#
#         if not os.path.exists(down_tar):
#             logging.info(f"Downloading tar.gz: {down_tar} from {ls_url}")
#             get_file(ls_url, down_tar)
#
#         logging.info(f"Extracting tar.gz: {down_tar}")
#         subprocess.call(["tar", "xzf", down_tar, "-C", untar_dir])
#
#     else:
#         logging.info(f"Scene already downloaded and extracted: {untar_dir}")


def band_name_landsat(prod_path):
    if "LE07_" in prod_path or "LT04_" in prod_path or "LT05_" in prod_path:
        return band_name_l7(prod_path)
    elif "LC08_" in prod_path:
        return band_name_l8(prod_path)
    else:
        logging.warning(f"unknown landsat product {prod_path}")
        raise Exception(f"unknown landsat product {prod_path}")


def band_name_l7(prod_path):
    """
        Determine l7 band of individual product from product name
        from path to specific product file

        Note this is used for Landsat 4, 5, and 7 as the bands we care about are the same in all three cases.
        """

    prod_name = os.path.basename(prod_path)
    parts = prod_name.split('_')
    prod_name = f"{parts[-2]}_{parts[-1][:-4]}"

    logging.debug("Product name is: {}".format(prod_name))

    prod_map = {
        "bt_band6": 'brightness_temperature_1',
        "pixel_qa": 'pixel_qa',
        "cloud_qa": 'sr_cloud_qa',
        "radsat_qa": 'radsat_qa',
        "atmos_opacity": 'sr_atmos_opacity',
        "sr_band1": 'blue',
        "sr_band2": 'green',
        "sr_band3": 'red',
        "sr_band4": 'nir',
        "sr_band5": 'swir1',
        "sr_band7": 'swir2',
    }

    layer_name = prod_map[prod_name]

    return layer_name


def band_name_l8(prod_path):
    """
    Determine l8 band of individual product from product name
    from path to specific product file
    """

    prod_name = os.path.basename(prod_path)
    parts = prod_name.split('_')
    prod_name = f"{parts[-2]}_{parts[-1][:-4]}".lower()

    if prod_name[:3] == "t1_" \
            or prod_name[:3] == "t2_" \
            or prod_name[:3] == "sr_" \
            or prod_name[:3] == "bt_":
        prod_name = prod_name[3:]

    logging.debug("Product name is: {}".format(prod_name))

    prod_map = {
        "pixel_qa": 'pixel_qa',
        "radsat_qa": 'radsat_qa',
        # "aerosol": 'sr_aerosol',
        "band1": 'coastal_aerosol',
        "band2": 'blue',
        "band3": 'green',
        "band4": 'red',
        "band5": 'nir',
        "band6": 'swir1',
        "band7": 'swir2',
        "band8": 'panchromatic',
        "band9": 'cirrus',
        "band10": 'brightness_temperature_1',
        "band11": 'brightness_temperature_2',
        "b1": 'coastal_aerosol',
        "b2": 'blue',
        "b3": 'green',
        "b4": 'red',
        "b5": 'nir',
        "b6": 'swir1',
        "b7": 'swir2',
        "b8": 'panchromatic',
        "b9": 'cirrus',
        "b10": 'brightness_temperature_1',
        "b11": 'brightness_temperature_2',
        "qa_radsat": 'radsat_qa',
        "qa_pixel": 'pixel_qa',
    }

    if prod_name in prod_map:
        layer_name = prod_map[prod_name]
    else:
        layer_name = "unknown"

    return layer_name


def conv_lsscene_cogs(untar_dir, cog_dir, overwrite=False):
    """
    Convert products to cogs [+ validate TBC].

    :param untar_dir: Downloaded S2 product directory (i.e. via ESA or GCloud; assumes .SAFE structure)
    :param cog_dir: directory in which to create the output COGs
    :param overwrite: Binary for whether to overwrite or skip existing COG files)
    :return: 
    """

    if not os.path.exists(untar_dir):
        logging.warning(
            'Cannot find original scene directory: {}'.format(untar_dir))

    # create cog scene directory
    if not os.path.exists(cog_dir):
        logging.info('Creating scene cog directory: {}'.format(cog_dir))
        os.mkdir(cog_dir)
    prod_paths = glob.glob(f"{untar_dir}/*.tif")

    # iterate over prods to create parellel processing list
    for prod in prod_paths:

        in_filename = prod
        out_filename = f"{cog_dir}{os.path.basename(in_filename)[:-4]}.tif"

        # ensure input file exists
        if os.path.exists(in_filename):

            # ensure output cog doesn't already exist
            if not os.path.exists(out_filename):
                conv_sgl_cog(in_filename, out_filename)

            else:
                logging.info('cog already exists: {}'.format(out_filename))
        else:
            logging.warning('cannot find product: {}'.format(in_filename))


def conv_sgl_cog(in_path, out_path):
    """
    Convert a single input file to COG format. Default settings via cogeo repository (funcs within prep_utils). 
    COG val TBC

    :param in_path: path to non-cog file
    :param out_path: path to new cog file
    :return: 
    """
    logging.debug(f"in: {in_path}, out: {out_path}")
    # set default cog profile (as recommended by alex leith)
    cog_profile = {
        'driver': 'GTiff',
        'interleave': 'pixel',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512,
        'compress': 'DEFLATE',
        'predictor': 2,
        'zlevel': 9
    }

    cog_translate(
        in_path,
        out_path,
        cog_profile,
        overview_level=5,
        overview_resampling='average'
    )

    ds = gdal.Open(in_path, gdal.GA_Update)
    if ds is not None:
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(0)
        b.FlushCache()
        b = None
        ds = None
    else:
        logging.info('not updated nodata')

    # should inc. cog val...


def copy_l8_metadata(untar_dir, cog_dir):

    metas = [fn for fn in glob.glob(f"{untar_dir}*") if
             (".tif" not in os.path.basename(fn)) & ("." in os.path.basename(fn))]
    logging.debug(metas)

    if metas:
        for meta in metas:

            n_meta = f"{cog_dir}{os.path.basename(meta)}"
            logging.info('native_meta: {}'.format(n_meta))

            # check meta file exists
            if os.path.exists(meta):
                # check cp doesn't exist
                if not os.path.exists(n_meta):
                    logging.info(
                        "Copying original metadata file to cog dir: {}".format(n_meta))
                    shutil.copyfile(meta, n_meta)
                else:
                    logging.info(
                        "Original metadata file already copied to cog_dir: {}".format(n_meta))
            else:
                logging.warning(
                    "Cannot find orignial metadata file: {}".format(meta))
    else:
        logging.warning(" No metadata to copy")


def find_l8_datetime(scene_dir):
    try:
        meta = glob.glob(f"{scene_dir}*.xml")[0]
        m = ET.parse(meta).getroot().findall(
            '{http://espa.cr.usgs.gov/v2}global_metadata')[0]
        d = m.find('{http://espa.cr.usgs.gov/v2}acquisition_date').text
        t = m.find('{http://espa.cr.usgs.gov/v2}scene_center_time').text
        return str(datetime.strptime(f"{d}{t[:8]}", '%Y-%m-%d%H:%M:%S'))
    except Exception:
        return str(datetime.strptime(f"{scene_dir.split('_')[-1][:-1]}", '%Y%m%d'))


def yaml_prep_landsat(scene_dir):
    """
    Prepare individual L8 scene directory containing L8 cog products converted
    from ESPA-ordered L1T scenes.
    """
    # scene_name = scene_dir.split('/')[-2][:26]
    scene_name = split_all(scene_dir)[-2]
    logging.info(f"Preparing scene {scene_name}")
    logging.info(f"Scene path {scene_dir}")

    # find all cog prods
    prod_paths = glob.glob(scene_dir + '*.tif')
    # print ( 'paths: {}'.format(prod_paths) )
    # for i in prod_paths: print ( i )
    logging.info(prod_paths)
    # date time assumed eqv for start and stop - this isn't true and could be
    # pulled from .xml file (or scene dir) not done yet for sake of progression
    t0 = parse(find_l8_datetime(scene_dir))

    images = {}
    for prod_path in prod_paths:
        name = band_name_landsat(prod_path)
        if name is not "unknown":
            images[name] = {
                'path': str(split_all(prod_path)[-1])
            }

    logging.info(images)

    # trusting bands coaligned, use one to generate spatial bounds for all
    projection, extent = get_geometry(
        os.path.join(str(scene_dir), images['blue']['path']))

    # parse esa l2a prod metadata file for reference
    scene_genesis = glob.glob(scene_dir + '*.xml')[0]
    if os.path.exists(scene_genesis):
        scene_genesis = os.path.basename(scene_genesis)
    else:
        scene_genesis = ' '

    new_id = str(uuid.uuid5(uuid.NAMESPACE_URL, scene_name))
    platform_code = ""
    instrument_name = ""
    if "LC08_" in scene_name:
        logging.info(f"{scene_name} detected as landsat 8")
        platform_code = "LANDSAT_8"
        instrument_name = "OLI"
    elif "LE07_" in scene_name:
        logging.info(f"{scene_name} detected as landsat 7")
        platform_code = "LANDSAT_7"
        instrument_name = "ETM"
    elif "LT05_" in scene_name:
        logging.info(f"{scene_name} detected as landsat 5")
        platform_code = "LANDSAT_5"
        instrument_name = "TM"
    elif "LT04_" in scene_name:
        logging.info(f"{scene_name} detected as landsat 4")
        platform_code = "LANDSAT_4"
        instrument_name = "TM"
    else:
        raise Exception(f"Unknown platform {scene_name}")

    return {
        'id': new_id,
        'processing_level': "espa_l2a2cog_ard",
        'product_type': "optical_ard",
        'creation_dt': str(datetime.today().strftime('%Y-%m-%d %H:%M:%S')),
        'platform': {
            'code': platform_code
        },
        'instrument': {
            'name': instrument_name
        },
        'extent': create_metadata_extent(extent, t0, t0),
        'format': {
            'name': 'GeoTiff'
        },
        'grid_spatial': {
            'projection': projection
        },
        'image': {
            'bands': images
        },
        'lineage': {
            'source_datasets': scene_genesis,
        }
    }


def prepareLS(in_scene, s3_bucket='', s3_dir='', prodlevel="", item=""):
    root = setup_logging()
    inter_dir = '/tmp/data/intermediate/'
    ls_url = in_scene
    downloaded_file_path, filenames = download_scene(
        ls_url, inter_dir + 'download/')
    logging.info(f"Downloaded {filenames}")
    filenames = [f for f in filenames if f.endswith(
        ('.tif', '.tiff', '.TIF', '.TIFF'))]
    logging.info(f"Filtered {filenames}")

    first_file = filenames[0]
    tokens = first_file.split('_')
    scene_name = '_'.join(tokens[:4])

    inter_dir = f"{inter_dir}{scene_name}_tmp/"
    os.makedirs(inter_dir, exist_ok=True)
    untar_dir = f"{inter_dir}{scene_name}_untar/"
    os.makedirs(untar_dir, exist_ok=True)
    cog_dir = f"{inter_dir}{scene_name}/"
    os.makedirs(cog_dir, exist_ok=True)

    logging.info(
        f"scene: {scene_name}\nuntar: {untar_dir}\ncog_dir: {cog_dir}")
    root.info(f"{scene_name} Starting")

    try:

        try:
            root.info(f"{scene_name} DOWNLOADING via ESPA")
            extract_scene(downloaded_file_path, untar_dir)
            root.info(f"{scene_name} DOWNLOADed + EXTRACTED")
        except Exception as e:
            root.exception(f"{scene_name} CANNOT BE FOUND")
            raise Exception('Download Error', e)

        try:
            root.info(f"{scene_name} Converting COGs")
            conv_lsscene_cogs(untar_dir, cog_dir)
            root.info(f"{scene_name} COGGED")
        except Exception as e:
            root.exception(f"{scene_name} CANNOT BE COGGED")
            raise Exception('COG Error', e)

        try:
            root.info(f"{scene_name} Copying medata")
            copy_l8_metadata(untar_dir, cog_dir)
            root.info(f"{scene_name} Copied medata")
        except Exception as e:
            root.exception(f"{scene_name} metadata not copied")
            raise Exception('Metadata copy error', e)

        try:
            root.info(f"{scene_name} Creating yaml")
            create_yaml(cog_dir, yaml_prep_landsat(cog_dir))
            root.info(f"{scene_name} Created yaml")
        except Exception as e:
            root.exception(f"{scene_name} yaml not created {e}")
            raise Exception('Yaml error', e)

        try:
            root.info(f"{scene_name} Uploading to S3 Bucket")
            s3_upload_cogs(glob.glob(cog_dir + '*'), s3_bucket, s3_dir)
            root.info(f"{scene_name} Uploaded to S3 Bucket")
        except Exception as e:
            root.exception(f"{scene_name} Upload to S3 Failed")
            raise Exception('S3  upload error', e)
    except Exception as e:
        logging.error(f"Could not process {scene_name}, {e}")
    finally:
        clean_up(inter_dir)

if __name__ == '__main__':
    prepareLS("https://edclpdsftp.cr.usgs.gov/orders/espa-Sarah.Cheesbrough@sa.catapult.org.uk-12022019-042034-386/LT040750721993010401T1-SC20191202114123.tar.gz")
