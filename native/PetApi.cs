using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

internal static class PetApi
{
    internal sealed class Command
    {
        public string id { get; set; }
        public string phase { get; set; }
        public string text { get; set; }
    }
    internal sealed class Status
    {
        public string headline { get; set; }
        public bool coding { get; set; }
        public int reviews { get; set; }
        public string reviewId { get; set; }
        public Command command { get; set; }
    }

    private static HttpWebRequest Request(string path)
    {
        var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + Program.Port + path);
        request.Proxy = null;
        request.AllowAutoRedirect = false;
        request.Timeout = 4000;
        request.ReadWriteTimeout = 4000;
        request.Accept = "application/json";
        return request;
    }

    internal static Task<Status> Read()
    {
        return Task.Run(delegate {
            var request = Request("/api/desktop");
            using (var response = request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8)) {
                if (response.ContentLength > 32768) throw new InvalidDataException();
                var status = new JavaScriptSerializer().Deserialize<Status>(reader.ReadToEnd());
                if (status == null || string.IsNullOrEmpty(status.headline)) throw new InvalidDataException();
                return status;
            }
        });
    }

    internal static Task Dispatch(string brief, string requestId)
    {
        return Task.Run(delegate {
            var request = Request("/api/tasks");
            request.Method = "POST";
            request.ContentType = "application/json; charset=utf-8";
            request.Headers["Origin"] = request.RequestUri.GetLeftPart(UriPartial.Authority);
            var payload = Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(new { brief, requestId }));
            request.ContentLength = payload.Length;
            using (var stream = request.GetRequestStream()) stream.Write(payload, 0, payload.Length);
            using (var response = (HttpWebResponse)request.GetResponse()) {
                if (response.StatusCode != HttpStatusCode.Created) throw new InvalidDataException();
            }
        });
    }
}
