# from odoo import http


# class Pdgs(http.Controller):
#     @http.route('/pdgs/pdgs', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/pdgs/pdgs/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('pdgs.listing', {
#             'root': '/pdgs/pdgs',
#             'objects': http.request.env['pdgs.pdgs'].search([]),
#         })

#     @http.route('/pdgs/pdgs/objects/<model("pdgs.pdgs"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('pdgs.object', {
#             'object': obj
#         })

