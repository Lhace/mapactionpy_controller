import json
import os
# from jsonschema import validate


class CrashMoveFolder:
    def __init__(self, cmf_path, verify_on_creation=True):

        self.path = os.path.dirname(cmf_path)
        
        with open(cmf_path, 'r') as f:
            obj = json.loads(f.read())

            # Doubtless there is a more elegant way to do this.
            #self.event_description_file = os.path.join(self.path, obj['event_description_file'])
            self.original_data = os.path.join(self.path, obj['original_data'])
            self.active_data = os.path.join(self.path, obj['active_data'])
            self.layer_rendering = os.path.join(self.path, obj['layer_rendering'])
            self.mxd_templates = os.path.join(self.path, obj['mxd_templates'])
            self.mxd_products = os.path.join(self.path, obj['mxd_products'])
            self.qgis_templates = os.path.join(self.path, obj['qgis_templates'])
            self.export_dir = os.path.join(self.path, obj['export_dir'])
            self.dnc_definition = os.path.join(self.path, obj['dnc_definition'])
            self.layer_nc_definition = os.path.join(self.path, obj['layer_nc_definition'])
            self.mxd_nc_definition = os.path.join(self.path, obj['mxd_nc_definition'])
            self.map_definitions = os.path.join(self.path, obj['map_definitions'])            
            self.layer_properties = os.path.join(self.path, obj['layer_properties'])       
            self.arcgis_version = obj['arcgis_version'] 
            self.categories = obj['categories'] 

        if verify_on_creation and (not self.verify_paths()):
            raise ValueError("Unable to verify existence of all files and directories defined in "
                             "CrashMoveFolder {}".format(cmf_path))

    def verify_paths(self):
        results = (
            # dirs
            os.path.isdir(self.original_data),
            os.path.isdir(self.active_data),
            os.path.isdir(self.layer_rendering),
            os.path.isdir(self.mxd_templates),
            os.path.isdir(self.mxd_products),
            os.path.isdir(self.qgis_templates),
            os.path.isdir(self.export_dir),
            # files
            #os.path.exists(self.event_description_file),
            os.path.exists(self.dnc_definition),
            os.path.exists(self.layer_nc_definition),
            os.path.exists(self.mxd_nc_definition),
            os.path.exists(self.map_definitions),
            os.path.exists(self.layer_properties),
            self.verify_mxds()
        )

        return all(results)

    def verify_mxds(self):
        result=True
        for category in (self.categories):
            for orientation in ['landscape', 'portrait']:
                templateFileName=self.arcgis_version + "_" + category + "_" + orientation

                if (category == "reference"):
                    templateFileName = templateFileName + "_bottom"
                templateFileName = templateFileName + ".mxd"       
                if (os.path.exists(os.path.join(self.mxd_templates, )) == False):
                    result = False
        return result        

